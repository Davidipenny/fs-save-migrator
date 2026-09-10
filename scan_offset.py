#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scan_offset.py — SteamID 偏移自动定位工具
==========================================
在解封装后的 USER_DATA_010 明文里搜索与存档文件夹名匹配的 8 字节序列，
自动定位各 FromSoftware 游戏的真实 SteamID 偏移。

用途：当 GAME_CONFIGS[*].steam_id_offset 存疑时，用真实存档反推正确偏移。

用法：
    python scan_offset.py [测试存档目录]

    默认测试存档目录：仓库根/可用于检验的存档
"""
import struct
import sys
from pathlib import Path

# 强制 UTF-8 输出
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# 导入主力包（脚本与包同目录）
PROJECT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT))

from fs_save_migrator import (
    GAME_CONFIGS,
    GameConfig,
    decrypt_user_data_entry,
    find_user_data_010,
    parse_bnd4_entries,
    parse_folder_name_steamid,
)

# ─── 测试存档目录 ────────────────────────────────────────────────────
# 默认用仓库根的测试存档集（.gitignore 排除，仅本地存在）；可用命令行参数覆盖
DEFAULT_TEST_DIR = PROJECT.parent / "可用于检验的存档"

# 游戏子目录名 → GAME_CONFIGS key（大小写/空格按实际存档目录名）
SUBDIR_TO_GAME_KEY = {
    "Darksouls3": "1",    # Dark Souls III
    "Darksouls2": "2",    # Dark Souls II / SOTFS
    "DARK SOULS REMASTERED": "3",  # DSR（目录名带空格）
    "Eldenring": "4",     # Elden Ring
    "Sekiro": "5",        # Sekiro
    "Nightreign": "6",    # Elden Ring Nightreign
}


# ─── 核心：扫描单个存档 ─────────────────────────────────────────────

def scan_one(sl2_path: Path, config: GameConfig) -> dict:
    """对单个 .sl2：解封装 USER_DATA_010，在明文里搜目标 SteamID 的 8 字节序列。"""
    result = {
        "file": sl2_path.name,
        "folder": sl2_path.parent.name,
        "game": config.name,
        "ok": False,
        "target_sid": None,
        "plain_len": 0,
        "hits_le": [],   # 小端序命中偏移
        "hits_be": [],   # 大端序命中偏移
        "error": None,
    }

    try:
        with open(sl2_path, "rb") as f:
            data = f.read()
    except OSError as e:
        result["error"] = "读取失败: %s" % e
        return result

    entries = parse_bnd4_entries(data)
    entry = find_user_data_010(entries)
    if not entry or entry.size == 0:
        result["error"] = "未找到 USER_DATA_010"
        return result

    # 解封装 USER_DATA_010（按 struct_type 三分支）
    plain = decrypt_user_data_entry(
        data, entry, bytes.fromhex(config.aes_key_hex), config.struct_type)
    if plain is None:
        result["error"] = "解封装失败（结构/密钥不符或数据过短）"
        return result

    result["plain_len"] = len(plain)

    # 目标 SteamID（用自动探测进制解析文件夹名）
    target = parse_folder_name_steamid(sl2_path.parent.name)
    if target is None:
        result["error"] = "文件夹名无法解析为 SteamID"
        return result
    result["target_sid"] = target

    tgt_le = struct.pack("<Q", target)   # 小端序 8 字节
    tgt_be = struct.pack(">Q", target)   # 大端序（保险）

    # 滑动搜索所有命中
    pos = 0
    while True:
        i = plain.find(tgt_le, pos)
        if i == -1:
            break
        result["hits_le"].append(i)
        pos = i + 1

    pos = 0
    while True:
        i = plain.find(tgt_be, pos)
        if i == -1:
            break
        result["hits_be"].append(i)
        pos = i + 1

    result["ok"] = True
    return result


# ─── 深度扫描：解封装所有 entry 搜索 ──────────────────────────────────

def deep_scan_one(sl2_path: Path, config: GameConfig) -> list:
    """解封装所有 USER_DATA entry，搜目标 SteamID64(8字节) 与 account_id(4字节)。

    account_id = SteamID64 - 0x0110000100000000 (SteamID32)。某些游戏可能存
    4 字节 account_id 而非完整 8 字节 SteamID64。
    """
    with open(sl2_path, "rb") as f:
        data = f.read()

    entries = parse_bnd4_entries(data)
    if not entries:
        return []

    target = parse_folder_name_steamid(sl2_path.parent.name)
    if target is None:
        return []
    tgt_le = struct.pack("<Q", target)          # SteamID64 小端 8 字节
    base = 0x0110000100000000
    account_id = target - base
    acct_le = struct.pack("<I", account_id) if 0 <= account_id < 2**32 else None
    key = bytes.fromhex(config.aes_key_hex)

    def find_all(haystack: bytes, needle: bytes) -> list:
        out, p = [], 0
        while True:
            i = haystack.find(needle, p)
            if i == -1:
                break
            out.append(i)
            p = i + 1
        return out

    results = []
    for e in entries:
        plain = decrypt_user_data_entry(data, e, key, config.struct_type)
        if plain is None:
            continue

        results.append({
            "entry": e.name, "plain_len": len(plain),
            "hits64": find_all(plain, tgt_le),
            "hits32": find_all(plain, acct_le) if acct_le else [],
        })
    return results


def print_deep(results: list):
    """打印深度扫描结果（ID64=8字节 SteamID64，ID32=4字节 account_id）"""
    if not results:
        print("  深度扫描: 无 entry 可扫描")
        return
    any_hit = False
    for r in results:
        h64, h32 = r["hits64"], r["hits32"]
        if h64 or h32:
            any_hit = True
            parts = []
            if h64:
                parts.append("ID64@%s" % fmt_hits(h64))
            if h32:
                parts.append("ID32@%s" % fmt_hits(h32))
            print("  [深扫] entry=%-16s 明文=%d字节  %s"
                  % (r["entry"], r["plain_len"], " | ".join(parts)))
    if not any_hit:
        print("  [深扫] 所有 %d 个 entry 解密后均无命中 (ID64/ID32 均无)"
              % len(results))


# ─── 格式化输出 ──────────────────────────────────────────────────────

def fmt_hits(hits):
    """把命中偏移列表格式化为 0xHH 字符串"""
    return ", ".join("0x%02X" % h for h in hits) if hits else "(无)"


def print_result(r: dict):
    print("  文件: %s" % r["file"])
    print("  游戏: %s" % r["game"])
    print("  文件夹名: %s" % r["folder"])
    if r["target_sid"] is not None:
        print("  目标 SteamID: %d (0x%X)" % (r["target_sid"], r["target_sid"]))
    if r["error"]:
        print("  状态: 错误 — %s" % r["error"])
        return
    print("  明文长度: %d 字节" % r["plain_len"])
    print("  小端序命中: %s" % fmt_hits(r["hits_le"]))
    print("  大端序命中: %s" % fmt_hits(r["hits_be"]))
    # 推断偏移
    le = r["hits_le"]
    if len(le) == 1:
        print("  >>> 推断 steam_id_offset = 0x%02X (小端序唯一命中) <<<" % le[0])
    elif len(le) > 1:
        # 优先 8 字节对齐的命中
        aligned = [h for h in le if h % 8 == 0]
        prefer = aligned if aligned else le
        print("  >>> 多候选(小端)，优先对齐/最小: 0x%02X (全部: %s) <<<"
              % (prefer[0], fmt_hits(le)))
    elif not r["hits_be"]:
        print("  >>> 无命中：SteamID 可能不在 USER_DATA_010，或存档与文件夹不匹配 <<<")


# ─── 主入口 ─────────────────────────────────────────────────────────

def main():
    test_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_TEST_DIR

    print("=" * 64)
    print("  scan_offset.py — SteamID 偏移自动定位")
    print("=" * 64)
    print("  测试存档目录: %s" % test_dir)
    print("  目录存在: %s" % test_dir.exists())

    if not test_dir.exists():
        print("\n  [FATAL] 目录不存在")
        sys.exit(2)

    # 收集所有 .sl2，按游戏分组
    sl2_files = sorted(test_dir.rglob("*.sl2"))
    print("  找到 %d 个 .sl2 文件\n" % len(sl2_files))

    if not sl2_files:
        print("  [FATAL] 未找到 .sl2")
        sys.exit(2)

    # 按游戏分组扫描
    by_game = {}
    for sl2 in sl2_files:
        # 找所属游戏子目录名
        rel = sl2.relative_to(test_dir)
        game_subdir = rel.parts[0] if rel.parts else ""
        game_key = SUBDIR_TO_GAME_KEY.get(game_subdir)
        if not game_key:
            print("  [SKIP] 未知游戏子目录: %s (文件 %s)" % (game_subdir, sl2.name))
            continue
        by_game.setdefault(game_key, []).append(sl2)

    summary = {}  # game_key -> 推断偏移
    for game_key, files in sorted(by_game.items()):
        config = GAME_CONFIGS[game_key]

        # folder 模式（DS2/DSR）：存档不内部绑定 SteamID，扫描无意义
        if config.bind_mode == "folder":
            print("\n" + "─" * 64)
            print("  游戏 [%s] %s" % (game_key, config.name))
            print("─" * 64)
            print("\n  [SKIP] folder 模式：存档不内部绑定 SteamID（靠文件夹名识别账号），无需扫描偏移")
            continue

        print("\n" + "─" * 64)
        print("  游戏 [%s] %s" % (game_key, config.name))
        print("  当前配置偏移: 0x%02X" % config.steam_id_offset)
        print("─" * 64)

        game_hits = []
        for sl2 in files:
            print()
            r = scan_one(sl2, config)
            print_result(r)
            if r["ok"] and len(r["hits_le"]) == 1:
                game_hits.append(r["hits_le"][0])
            elif r["ok"] and not r["hits_le"] and not r["hits_be"]:
                # USER_DATA_010 无命中，深度扫描所有 entry
                print("  --- 深度扫描（解密所有 entry 搜索）---")
                deep = deep_scan_one(sl2, config)
                print_deep(deep)

        # 游戏级推断
        if game_hits:
            # 所有存档一致命中 → 高置信
            unique = set(game_hits)
            if len(unique) == 1:
                off = game_hits[0]
                summary[game_key] = off
                print("\n  [游戏结论] %s steam_id_offset = 0x%02X (全部存档一致)"
                      % (config.name, off))
            else:
                print("\n  [游戏结论] %s 多存档命中不一致: %s"
                      % (config.name, ", ".join("0x%02X" % h for h in game_hits)))
        else:
            print("\n  [游戏结论] %s 无唯一命中，需人工判断" % config.name)

    # ─── 汇总 ───────────────────────────────────────────────────
    print("\n" + "=" * 64)
    print("  汇总：建议更新的 steam_id_offset")
    print("=" * 64)
    for game_key in sorted(by_game.keys()):
        config = GAME_CONFIGS[game_key]
        if config.bind_mode == "folder":
            print("  [%s] %-28s folder 模式（不内部绑定 SteamID，偏移不适用）"
                  % (game_key, config.name))
            continue
        cur = config.steam_id_offset
        if game_key in summary:
            new = summary[game_key]
            mark = "(已一致，无需改)" if new == cur else "  <-- 建议改"
            print("  [%s] %-28s 当前=0x%02X  建议=0x%02X  %s"
                  % (game_key, config.name, cur, new, mark))
        else:
            print("  [%s] %-28s 当前=0x%02X  (无定论，保留)"
                  % (game_key, config.name, cur))
    print("=" * 64)


if __name__ == "__main__":
    main()
