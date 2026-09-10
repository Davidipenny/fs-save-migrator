"""交互式 CLI 菜单
==================

运行后：选择游戏 → 选择源/目标存档（扫描列表或手动路径）→ 选择方向 → 确认迁移。
"""
import shutil
import sys
from pathlib import Path

from .games import GAME_CONFIGS, GameConfig
from .migrate import (
    extract_steam_id,
    parse_folder_name_steamid,
    patch_steam_id,
    scan_save_folders,
)

# ─── 手动指定存档 ─────────────────────────────────────────────────────

def manual_select_save_file(config: GameConfig) -> Path | None:
    """手动指定存档文件路径"""
    print("\n  请输入存档文件的完整路径 (.sl2 或 .co2)")
    print("  (例如: C:\\Users\\xxx\\AppData\\Roaming\\%s\\xxxxx\\DS30000.sl2)" % config.appdata_dir)
    print("  (黑盒语音备份: D:\\...\\Eldenring\\ER0000--xxxx----\\ER0000.co2)")
    path_str = input("  路径: ").strip().strip('"').strip("'")
    if not path_str:
        return None
    p = Path(path_str)
    if p.exists() and p.is_file():
        return p
    print("  [!] 文件不存在: %s" % p)
    return None


# ─── 交互菜单 ──────────────────────────────────────────────────────────

def select_game() -> tuple[str, GameConfig]:
    """选择游戏"""
    print("\n" + "=" * 60)
    print("  FS Save Migrator — FromSoftware 存档通用迁移工具 v2")
    print("=" * 60)
    print("\n支持的遊戲:")
    for k, v in GAME_CONFIGS.items():
        print("  [%s] %s  (%s)" % (k, v.name, v.notes))
    print("  [q] 退出")
    while True:
        choice = input("\n请选择游戏: ").strip()
        if choice.lower() == "q":
            sys.exit(0)
        if choice in GAME_CONFIGS:
            return choice, GAME_CONFIGS[choice]
        print("  无效选择")


def choose_save(folders: list[tuple[Path, str]], config: GameConfig,
                role: str) -> tuple[Path, str, Path | None] | None:
    """选择源或目标存档。返回 (folder_path, steam_id_hex, sl2_file) 或 None。

    支持两种方式：从 %APPDATA% 扫描列表选，或直接输入文件路径
    (.sl2 或 .co2，兼容黑盒语音等第三方备份)。
    """
    print("\n  --- 选择%s存档 ---" % role)
    print("  [1] 从扫描列表选择" + (" (找到 %d 个)" % len(folders) if folders else " (扫描为空)"))
    print("  [2] 直接输入存档文件路径 (.sl2 或 .co2)")
    while True:
        c = input("  请选择 (1 或 2): ").strip()
        if c == "1":
            if not folders:
                print("  [!] 扫描列表为空，请用选项 2 手动指定路径")
                continue
            print("\n  找到 %d 个存档文件夹:\n" % len(folders))
            for i, (path, _hex_str) in enumerate(folders):
                sl2_files = list(path.glob(config.file_ext))
                sid_info = ""
                if sl2_files:
                    sid = extract_steam_id(sl2_files[0], config)
                    if sid:
                        sid_info = "  [存档内 SteamID: %s]" % sid
                folder_sid = parse_folder_name_steamid(path.name)
                print("  [%d] %s  (文件夹名->SteamID: %s)%s"
                      % (i, path.name, folder_sid if folder_sid else "?", sid_info))
            while True:
                try:
                    idx = int(input("  %s存档编号: " % role))
                    if 0 <= idx < len(folders):
                        break
                except ValueError:
                    pass
                print("  请输入 0-%d" % (len(folders) - 1))
            p, h = folders[idx]
            sl2 = list(p.glob(config.file_ext))
            sl2_file = sl2[0] if sl2 else None
            if not sl2_file:
                # 也尝试 .co2（黑盒语音等第三方备份）
                co2 = list(p.glob("*.co2"))
                sl2_file = co2[0] if co2 else None
            return p, h, sl2_file
        elif c == "2":
            f = manual_select_save_file(config)
            if not f:
                print("  未指定，请重新选择")
                continue
            return f.parent, f.parent.name, f
        else:
            print("  请输入 1 或 2")


# ─── 主流程 ────────────────────────────────────────────────────────────

def main() -> None:
    game_key, config = select_game()

    print("\n扫描 %%APPDATA%%\\%s\\ ..." % config.appdata_dir)
    folders = scan_save_folders(config)

    src = choose_save(folders, config, "源")
    if not src:
        return
    src_path, src_steam_id_hex, src_sl2 = src

    dst = choose_save(folders, config, "目标")
    if not dst:
        return
    dst_path, dst_steam_id_hex, dst_sl2 = dst

    src_sid = extract_steam_id(src_sl2, config) if src_sl2 else None
    dst_sid = extract_steam_id(dst_sl2, config) if dst_sl2 else None

    print("\n  ┌─ 源存档: %s" % src_path.name)
    print("  │  文件夹名 (SteamID): %s" % src_steam_id_hex)
    if config.bind_mode == "folder":
        print("  │  存档内 SteamID: 不内部绑定（该游戏靠文件夹名识别账号）")
    elif src_sid:
        print("  │  存档内 SteamID (十进制):    %s (0x%s)" % (src_sid, format(src_sid, "x")))
    else:
        print("  │  存档内 SteamID: 未能读取")

    print("  ├─ 目标存档: %s" % dst_path.name)
    print("  │  文件夹名 (SteamID): %s" % dst_steam_id_hex)
    # 目标 SteamID 优先从存档内部读取（支持 .co2 等文件夹名非 SteamID 的备份），否则用文件夹名
    dst_target_sid = dst_sid if dst_sid else parse_folder_name_steamid(dst_steam_id_hex)
    if dst_sid:
        print("  │  存档内 SteamID (十进制):    %s (0x%s)" % (dst_sid, format(dst_sid, "x")))
    print("  │  目标 SteamID (十进制):       %s" % dst_target_sid)

    print("\n  └─ 转换方向:")
    print("     [1] 源 → 目标  (将源存档的SteamID改为目标的)")
    print("     [2] 目标 → 源  (将目标存档的SteamID改为源的)")
    while True:
        try:
            direction = int(input("  请选择 (1 或 2): "))
            if direction in (1, 2):
                break
        except ValueError:
            pass
        print("  请输入 1 或 2")

    if direction == 1:
        if not src_sl2:
            print("\n  [!] 源文件夹中没有存档文件，无法正向。")
            return
        if dst_target_sid is None:
            print("\n  [!] 无法确定目标 SteamID（存档不可读且文件夹名无法解析）。")
            return
        source_file = src_sl2
        new_sid = dst_target_sid
        output_dir = dst_path
        desc = "将 %s 的存档迁移到 %s" % (src_path.name, dst_path.name)
    else:
        if not dst_sl2:
            print("\n  [!] 目标文件夹中没有存档文件，无法反向。")
            return
        source_file = dst_sl2
        # 源 SteamID 优先从存档内部读取（支持 .co2 等备份），否则用文件夹名
        src_target_sid = src_sid if src_sid else parse_folder_name_steamid(src_steam_id_hex)
        if src_target_sid is None:
            print("\n  [!] 无法确定源 SteamID（存档不可读且文件夹名无法解析）。")
            return
        new_sid = src_target_sid
        output_dir = src_path
        desc = "将 %s 的存档迁移到 %s" % (dst_path.name, src_path.name)

    print("\n  ⚠️  即将执行: %s" % desc)
    if config.bind_mode == "folder":
        print("  (该游戏不内部绑定 SteamID，将直接复制存档到目标文件夹，不改存档内部)")
    else:
        print("  目标 SteamID: %s (0x%s)" % (new_sid, format(new_sid, "x")))
    confirm = input("  确认? (y/N): ").strip().lower()
    if confirm != "y":
        print("  已取消。")
        return

    output_name = source_file.name
    output_path = output_dir / output_name

    if output_path.exists():
        bak = output_dir / (output_name + ".bak")
        print("\n  备份原文件 → %s" % bak.name)
        shutil.copy2(output_path, bak)

    print("\n  正在修改存档 SteamID...")
    ok = patch_steam_id(source_file, new_sid, output_path, config)

    if ok:
        print("\n  ✅ 迁移成功！")
        print("  输出: %s" % output_path)
        print("  启动游戏即可读取存档。")
    else:
        print("\n  ❌ 迁移失败！")

    input("\n按 Enter 退出...")
