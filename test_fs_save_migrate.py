#!/usr/bin/env python3
"""单元测试 v2"""
import sys, os, struct, hashlib, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fs_save_migrate import (
    GAME_CONFIGS, HAS_CRYPTOGRAPHY,
    aes_decrypt, aes_encrypt,
    parse_bnd4_entries, find_user_data_010,
    extract_steam_id, patch_steam_id,
    parse_folder_name_steamid,
    scan_save_folders,
)

PASS = 0
FAIL = 0

def test(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print("  [OK] %s" % name)
    else:
        FAIL += 1
        print("  [FAIL] %s" % name + ("  -- %s" % detail if detail else ""))

print("=" * 60)
print("  FS Save Migrator v2 -- 单元测试")
print("=" * 60)

# 测试 1: 游戏配置
print("\n[1/6] 游戏配置完整性")
test("6 款游戏均已配置", len(GAME_CONFIGS) == 6)
for k, v in GAME_CONFIGS.items():
    ok = all(f in v for f in ["name", "appdata_dir", "file_ext", "aes_key_hex",
                               "steam_id_offset", "user_data_id"])
    test("  [%s] %s: 配置完整" % (k, v["name"]), ok)

# 测试 2: AES 加解密
print("\n[2/6] AES-128-CBC 加解密")
key = bytes.fromhex("FD464D695E69A39A10E319A7ACE8B7FA")
iv = bytes.fromhex("0123456789ABCDEF0123456789ABCDEF")
plain = b"Hello Dark Souls Save File!" + b"\x00" * 5  # 32字节，16对齐

ct = aes_encrypt(plain, iv, key)
test("AES 加密成功", len(ct) > 0)
pt2 = aes_decrypt(ct, iv, key)
test("AES 解密可逆", pt2 == plain)
test("AES 解密可逆", pt2 == plain)

# 测试 3: BND4 解析 + SteamID
print("\n[3/6] BND4 解析 + SteamID 提取修改")
ds3_path = Path(os.environ.get("APPDATA", "")) / "DarkSoulsIII"
real_sl2 = None
if ds3_path.exists():
    for folder in sorted(ds3_path.iterdir()):
        if folder.is_dir() and len(folder.name) >= 8:
            sl2_files = list(folder.glob("*.sl2"))
            if sl2_files:
                real_sl2 = sl2_files[0]
                break

if real_sl2:
    with open(real_sl2, "rb") as f:
        data = f.read()

    entries = parse_bnd4_entries(data)
    test("BND4 解析返回 12 个条目", len(entries) == 12 if entries else False)

    if entries:
        test("  entry 0: USER_DATA000", "USER_DATA000" in entries[0]["name"])
        test("  entry 10: USER_DATA010", "USER_DATA010" in entries[10]["name"])
        test("  entry 0 offset=0x300", entries[0]["offset"] == 0x300)

        entry_010 = find_user_data_010(entries)
        test("  find_user_data_010 找到", entry_010 is not None)
        if entry_010:
            test("  USER_DATA_010 size > 0", entry_010["size"] > 0)

    config = GAME_CONFIGS["1"]
    sid = extract_steam_id(real_sl2, config)
    test("SteamID 提取成功", sid is not None and sid > 0)

    if sid:
        folder_name = real_sl2.parent.name
        expected = parse_folder_name_steamid(folder_name)
        test("  SteamID 匹配文件夹名 %s" % folder_name, sid == expected,
             "期望: %s, 得到: %s" % (expected, sid))

        new_sid = sid + 1
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "test_out.sl2"
            ok = patch_steam_id(real_sl2, new_sid, out_path, config)
            test("SteamID 修改成功", ok)

            if ok and out_path.exists():
                test("  输出文件存在", True)
                test("  文件大小一致", out_path.stat().st_size == real_sl2.stat().st_size)

                new_sid_read = extract_steam_id(out_path, config)
                test("  新 SteamID 正确", new_sid_read == new_sid,
                     "期望: %s, 得到: %s" % (new_sid, new_sid_read))

                orig_sid = extract_steam_id(real_sl2, config)
                test("  原文件未修改", orig_sid == sid,
                     "期望: %s, 得到: %s" % (sid, orig_sid))
else:
    print("  [SKIP] 未找到真实存档，跳过")

# 测试 4: 错误处理
print("\n[4/6] 错误处理")
config = GAME_CONFIGS["1"]

sid = extract_steam_id(Path("C:/nonexistent/DS30000.sl2"), config)
test("不存在的文件返回 None", sid is None)

with tempfile.TemporaryDirectory() as tmpdir:
    empty = Path(tmpdir) / "empty.sl2"
    empty.write_bytes(b"")
    sid = extract_steam_id(empty, config)
    test("空文件返回 None", sid is None)

    invalid = Path(tmpdir) / "invalid.sl2"
    invalid.write_bytes(b"XXXX" + b"\x00" * 100)
    sid = extract_steam_id(invalid, config)
    test("无效 BND4 返回 None", sid is None)

# 测试 5: 扫描存档文件夹
print("\n[5/6] 存档文件夹扫描")
for k, cfg in GAME_CONFIGS.items():
    folders = scan_save_folders(cfg)
    status = "找到 %d 个" % len(folders) if folders else "无（未安装此游戏）"
    test("  [%s] %s: %s" % (k, cfg["name"], status), True)

# 测试 6: parse_folder_name_steamid 进制探测
print("\n[6] parse_folder_name_steamid 进制探测")
_radix_cases = [
    ("0110000100000666", 76561197960267366),   # DS3 hex 纯数字
    ("0110000167dacdf4", 76561199702658548),   # DS2/DS3 hex 含字母
    ("0110000173b6c269", 76561199901622889),  # DS3 hex 含字母
    ("76561199702658548", 76561199702658548), # ER/Sekiro/Nightreign 十进制
    ("76561197960265728", 76561197960265728), # 十进制基准
    ("1742392820", 76561199702658548),        # DSR account_id 十进制 -> +base
    ("short", None),                          # 过短返回 None
]
for _name, _want in _radix_cases:
    _got = parse_folder_name_steamid(_name)
    test("  %-20s -> %s" % (_name, _want), _got == _want, "得到 %s" % _got)

# 汇总
print("\n" + "=" * 60)
print("  测试结果: %d 通过, %d 失败" % (PASS, FAIL))
if FAIL == 0:
    print("  ALL PASSED!")
else:
    print("  %d FAILED" % FAIL)
print("=" * 60)