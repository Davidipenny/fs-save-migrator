"""命令行入口：交互式菜单 + argparse 非交互模式
================================================

- 无参数运行 → 交互式菜单（原行为）
- 带 --game/--src/--dst → 非交互迁移，适合脚本化调用

非交互示例：
  fs-save-migrator --game ds3 --src "C:\\src\\DS30000.sl2" --dst "C:\\dst\\01100001..." --yes
  fs-save-migrator --game er --src ER0000.sl2 --dst 76561199... --dry-run

退出码：0 成功 / 1 迁移失败或取消 / 2 用法错误（argparse 原生）
"""
import argparse
import shutil
import sys
from pathlib import Path

from .games import GAME_CONFIGS, GameConfig
from .migrate import (
    extract_steam_id,
    get_save_roots,
    parse_folder_name_steamid,
    patch_steam_id,
    scan_save_folders,
)

# ─── 游戏别名（argparse --game 用）────────────────────────────────────

GAME_ALIASES: dict[str, str] = {
    "ds3": "1", "ds2": "2", "dsr": "3",
    "er": "4", "eldenring": "4", "elden-ring": "4",
    "sekiro": "5",
    "nr": "6", "nightreign": "6",
}
GAME_ALIASES.update({str(k): k for k in GAME_CONFIGS})  # 也接受 1-6


# ─── 迁移执行（交互/非交互共用）──────────────────────────────────────

def find_save_in_dir(directory: Path, config: GameConfig) -> Path | None:
    """目录内找存档文件：优先 file_ext（.sl2），回退 .co2（黑盒备份）。"""
    sl2 = list(directory.glob(config.file_ext))
    if sl2:
        return sl2[0]
    co2 = list(directory.glob("*.co2"))
    return co2[0] if co2 else None


def resolve_save_arg(path_str: str, config: GameConfig, role: str,
                     require_file: bool = True) -> tuple[Path, Path | None] | None:
    """解析 --src/--dst：文件或目录 → (归属文件夹, 存档文件或 None)。

    - require_file=True（源）：目录中必须已有存档文件
    - require_file=False（目标）：允许空目录/新建目录（目标账号文件夹
      可能尚无存档，SteamID 由文件夹名推导，见 README 场景 1）
    """
    p = Path(path_str.strip().strip('"'))
    if p.is_file():
        return p.parent, p
    if p.is_dir():
        save = find_save_in_dir(p, config)
        if save or not require_file:
            return p, save
        print("  [!] %s 目录中未找到存档文件 (%s)：%s"
              % (role, config.file_ext, p))
        return None
    print("  [!] %s 路径不存在: %s" % (role, p))
    return None


def derive_target_sid(dst_dir: Path, dst_save: Path | None,
                      config: GameConfig) -> int | None:
    """推导目标 SteamID：优先存档内部（支持 .co2 等异名备份），回退文件夹名。"""
    sid = extract_steam_id(dst_save, config) if dst_save else None
    if sid:
        return sid
    return parse_folder_name_steamid(dst_dir.name)


def perform_migration(source_file: Path, new_sid: int, output_dir: Path,
                      config: GameConfig, dry_run: bool) -> bool:
    """执行迁移（含 .bak 备份）。dry_run=True 只打印计划，不写任何文件。"""
    output_path = output_dir / source_file.name

    print("\n  ┌─ 迁移计划")
    print("  │  源存档:   %s" % source_file)
    print("  │  输出至:   %s" % output_path)
    if config.bind_mode == "folder":
        print("  │  方式:     纯复制（该游戏不内部绑定 SteamID，靠文件夹名识别账号）")
    else:
        print("  │  新 SteamID: %s (0x%s)" % (new_sid, format(new_sid, "x")))
    if output_path.exists():
        print("  │  备份:     %s.bak（写入前自动创建）" % output_path.name)
    print("  └─" if dry_run else "  └─ 开始执行...")

    if dry_run:
        print("\n  (dry-run 模式：仅显示计划，未写入任何文件)")
        return True

    if output_path.exists():
        bak = output_dir / (output_path.name + ".bak")
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
    return ok


# ─── 非交互模式 ───────────────────────────────────────────────────────

def run_non_interactive(args: argparse.Namespace) -> int:
    config = GAME_CONFIGS[GAME_ALIASES[args.game]]

    src = resolve_save_arg(args.src, config, "源", require_file=True)
    if not src:
        return 2
    src_dir, src_save = src
    if src_save is None:  # require_file=True 之下不会发生，类型上仍需收窄
        print("  [!] 源路径中未找到存档文件")
        return 2

    dst = resolve_save_arg(args.dst, config, "目标", require_file=False)
    if not dst:
        return 2
    dst_dir, dst_save = dst

    if dst_save and src_save == dst_save:
        print("  [!] 源与目标是同一个文件")
        return 2

    if args.direction == 1:
        source_file, output_dir = src_save, dst_dir
        target_sid_save, target_sid_dir = dst_save, dst_dir
    else:
        if dst_save is None:
            print("  [!] 目标文件夹中没有存档文件，无法反向。")
            return 2
        source_file, output_dir = dst_save, src_dir
        # 反向：新 sid 取源侧（内部 sid 优先，回退源文件夹名）
        target_sid_save, target_sid_dir = src_save, src_dir

    if config.bind_mode == "folder":
        new_sid = 0  # folder 模式不用 sid，占位
    else:
        sid = derive_target_sid(target_sid_dir, target_sid_save, config)
        if sid is None:
            print("  [!] 无法确定目标 SteamID（存档不可读且文件夹名无法解析）")
            return 2
        new_sid = sid

    print("游戏: %s  |  绑定方式: %s" % (config.name, config.bind_mode))
    if args.dry_run:
        perform_migration(source_file, new_sid, output_dir, config, dry_run=True)
        return 0

    if not args.yes:
        answer = input("  确认执行? (y/N): ").strip().lower()
        if answer != "y":
            print("  已取消。")
            return 1

    return 0 if perform_migration(source_file, new_sid, output_dir,
                                  config, dry_run=False) else 1


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

    支持两种方式：从扫描列表选，或直接输入文件路径
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
            return p, h, find_save_in_dir(p, config)
        elif c == "2":
            f = manual_select_save_file(config)
            if not f:
                print("  未指定，请重新选择")
                continue
            return f.parent, f.parent.name, f
        else:
            print("  请输入 1 或 2")


# ─── 主流程（交互式）───────────────────────────────────────────────────

def main_interactive() -> None:
    game_key, config = select_game()

    roots = get_save_roots(config)
    print("\n扫描存档目录:")
    for r in roots:
        print("  - %s%s" % (r, "" if r.exists() else "  (不存在)"))
    folders = scan_save_folders(config)
    if folders:
        print("  共找到 %d 个存档文件夹" % len(folders))

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

    if config.bind_mode == "folder":
        print("\n  ⚠️  即将复制存档（该游戏不内部绑定 SteamID，不改存档内部）")
    else:
        print("\n  ⚠️  即将把存档 SteamID 改为 %s (0x%s)" % (new_sid, format(new_sid, "x")))
    confirm = input("  确认? (y/N): ").strip().lower()
    if confirm != "y":
        print("  已取消。")
        return

    perform_migration(source_file, new_sid, output_dir, config, dry_run=False)
    input("\n按 Enter 退出...")


# ─── argparse 入口 ────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fs-save-migrator",
        description="FromSoftware 存档通用迁移工具（只改 SteamID，不动游戏数据）。"
                    "不带参数运行进入交互式菜单。",
        epilog="示例：fs-save-migrator --game ds3 --src <源.sl2> --dst <目标文件夹> --yes",
    )
    parser.add_argument(
        "--game", metavar="GAME",
        help="游戏：ds3/ds2/dsr/er/sekiro/nr 或 1-6（缺省则进入交互式菜单）")
    parser.add_argument("--src", help="源存档路径（.sl2/.co2 文件或其所在文件夹）")
    parser.add_argument("--dst", help="目标存档路径（文件或文件夹；迁移写入此处）")
    parser.add_argument("--direction", type=int, choices=(1, 2), default=1,
                        help="1=源→目标（默认），2=目标→源")
    parser.add_argument("--yes", "-y", action="store_true",
                        help="跳过确认提示（.bak 备份始终执行，无法关闭）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只显示迁移计划，不写入任何文件")
    parser.add_argument("--version", action="version",
                        version="fs-save-migrator 2.0.0")
    return parser


def main(argv: list[str] | None = None) -> int:
    """包入口：无 --game 时保持交互式菜单原行为。"""
    # UTF-8 输出（PyInstaller exe / 管道重定向时防中文乱码；控制台直连时为 no-op）
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except Exception:
            pass

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.game is None:
        if args.src or args.dst:
            parser.error("--src/--dst 需要与 --game 一起使用")
        main_interactive()
        return 0

    if not args.src or not args.dst:
        parser.error("非交互模式需要 --src 和 --dst")
    return run_non_interactive(args)
