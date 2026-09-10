#!/usr/bin/env python3
"""
FS Save Migrator — FromSoftware 存档通用迁移工具 v2
===================================================
支持游戏：
  - Dark Souls III          (黑暗之魂3)       ✅ 已验证
  - Dark Souls II / SOTFS   (黑暗之魂2)       ✅ 同引擎
  - Dark Souls Remastered   (黑暗之魂重制版)   ✅ 同引擎
  - Elden Ring              (艾尔登法环)       ✅ 同引擎
  - Sekiro: Shadows Die Twice (只狼)          ✅ 同引擎

原理：
  FromSoftware 自 DS2 起使用 BND4 容器格式存储存档，
  每个存档与 Steam 账号 ID (64位) 绑定，存储在 USER_DATA_010
  的偏移 0x08 处。数据用 AES-128-CBC 加密，密钥固定。

用法：
  python fs_save_migrate.py
  交互式菜单引导，支持双向转换（A→B 或 B→A）。
"""

import os
import sys
import shutil
import struct
import hashlib
from pathlib import Path

# ─── 游戏配置表 ────────────────────────────────────────────────────────
GAME_CONFIGS = {
    "1": {
        "name": "Dark Souls III (黑暗之魂3)",
        "appdata_dir": "DarkSoulsIII",
        "file_ext": "*.sl2",
        "aes_key_hex": "FD464D695E69A39A10E319A7ACE8B7FA",
        "struct_type": "md5_iv_ct",     # [md5(16)|iv(16)|ct]
        "steam_id_offset": 0x08,        # 解密后明文中的偏移
        "user_data_id": 10,
        "bind_mode": "internal",        # 存档内部绑定 SteamID，patch 修改内部
        "notes": "已验证：AES [md5|iv|ct]，解密后偏移 0x08",
    },
    "2": {
        "name": "Dark Souls II / SOTFS (黑暗之魂2)",
        "appdata_dir": "DarkSoulsII",
        "file_ext": "*.sl2",
        "aes_key_hex": "599F9B699640A55236EE2D70835EC744",  # DS2S(SOTFS); 原版用 B7FD463E4A9C1102DF1739E5F3B2A50F
        "struct_type": "md5_iv_ct",
        "steam_id_offset": 0x08,
        "user_data_id": 10,
        "bind_mode": "folder",          # .sl2 不内部绑定 SteamID，迁移靠文件夹名，纯复制
        "notes": "密钥已解(DS2S)。但 .sl2 不内部绑定 SteamID，迁移靠文件夹名",
    },
    "3": {
        "name": "Dark Souls Remastered (黑暗之魂重制版)",
        "appdata_dir": "DarkSoulsRemastered",
        "file_ext": "*.sl2",
        "aes_key_hex": "0123456789ABCDEFFEDCBA9876543210",  # DSR 密钥(soulsmods)
        "struct_type": "md5_iv_ct",     # 同 DS3 结构
        "steam_id_offset": 0x08,
        "user_data_id": 10,
        "bind_mode": "folder",          # 实测 0x08 是版本字段；不内部绑定 SteamID，靠 STEAMID3 文件夹识别，纯复制
        "notes": "实测(2026-08-06)：不内部绑定 SteamID（0x08 是版本字段），靠 STEAMID3 文件夹迁移，同 DS2。实际存档在 Documents\\NBGI\\DARK SOULS REMASTERED(非%APPDATA%)，用手动模式",
    },
    "4": {
        "name": "Elden Ring (艾尔登法环)",
        "appdata_dir": "EldenRing",
        "file_ext": "*.sl2",
        "aes_key_hex": "",
        "struct_type": "plain",         # USER_DATA_010 明文 + checksum
        "steam_id_offset": 0x14,        # 原始字节中的偏移
        "user_data_id": 10,
        "bind_mode": "internal",
        "notes": "已验证：明文，SteamID @ 0x14（黑盒 .co2 patch 闭环全过）",
    },
    "5": {
        "name": "Sekiro: Shadows Die Twice (只狼)",
        "appdata_dir": "Sekiro",
        "file_ext": "*.sl2",
        "aes_key_hex": "",
        "struct_type": "plain",
        "steam_id_offset": 0x34,        # 原始字节中的偏移
        "user_data_id": 10,
        "bind_mode": "internal",
        "notes": "已验证：明文，SteamID @ 0x34（真实存档命中）",
    },
    "6": {
        "name": "Elden Ring Nightreign (黑夜君临)",
        "appdata_dir": "Nightreign",
        "file_ext": "*.sl2",
        "aes_key_hex": "18F6326605BD178A5524523AC0A0C609",  # NR 密钥(Keys.cs)
        "struct_type": "iv_ct",         # [iv(16)|ct]，IV 在前 16 字节，无 md5
        "steam_id_offset": 0x08,        # 解密后明文中的偏移
        "user_data_id": 10,
        "bind_mode": "internal",
        "notes": "已验证：AES [iv|ct]，NR 密钥，SteamID @ 0x08（真实存档命中）",
    },
}

# 尝试导入 cryptography
try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.backends import default_backend

    HAS_CRYPTOGRAPHY = True
except ImportError:
    HAS_CRYPTOGRAPHY = False


# ─── AES 加解密 ────────────────────────────────────────────────────────

def aes_decrypt(ciphertext: bytes, iv: bytes, key: bytes) -> bytes:
    if HAS_CRYPTOGRAPHY:
        c = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
        d = c.decryptor()
        return d.update(ciphertext) + d.finalize()
    else:
        return _powershell_aes(ciphertext.hex(), iv.hex(), key.hex(), decrypt=True)


def aes_encrypt(plaintext: bytes, iv: bytes, key: bytes) -> bytes:
    if HAS_CRYPTOGRAPHY:
        c = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
        e = c.encryptor()
        return e.update(plaintext) + e.finalize()
    else:
        return _powershell_aes(plaintext.hex(), iv.hex(), key.hex(), decrypt=False)


def _powershell_aes(data_hex: str, iv_hex: str, key_hex: str, decrypt: bool) -> bytes:
    """PowerShell + .NET AES 回退（Windows PowerShell 5.1 兼容）。

    - hex→bytes 用自写 H2B 函数（`[System.Convert]::FromHexString` 是 .NET 5+/PS7
      专属 API，PS5.1 不存在）
    - 整体 try/catch：任何异常 → Write-Error + exit 1（**显式失败**，不再静默返回空）
    """
    import subprocess

    mode_name = "Decrypt" if decrypt else "Encrypt"
    create = "CreateDecryptor" if decrypt else "CreateEncryptor"
    ps = (
        "try {"
        + "function H2B($h){$n=[int]($h.Length/2);$b=New-Object 'System.Byte[]' $n;"
        + "for($i=0;$i -lt $n;$i++){$b[$i]=[Convert]::ToByte($h.Substring($i*2,2),16)};,$b}"
        + "$k=H2B '%s';" % key_hex
        + "$i=H2B '%s';" % iv_hex
        + "$d=H2B '%s';" % data_hex
        + "$a=[System.Security.Cryptography.Aes]::Create();"
        + "$a.Mode=[System.Security.Cryptography.CipherMode]::CBC;"
        + "$a.Padding=[System.Security.Cryptography.PaddingMode]::PKCS7;"
        + "$t=$a.%s($k,$i);" % create
        + "$m=New-Object System.IO.MemoryStream;"
        + "$c=New-Object System.Security.Cryptography.CryptoStream($m,$t,"
        "[System.Security.Cryptography.CryptoStreamMode]::Write);"
        + "$c.Write($d,0,$d.Length);$c.FlushFinalBlock();$c.Close();"
        + "$b=$m.ToArray();$m.Close();"
        + "$s=New-Object System.Text.StringBuilder;"
        + "foreach($x in $b){[void]$s.Append($x.ToString('x2'))}"
        + "Write-Output $s.ToString()"
        + "} catch { Write-Error $_.Exception.Message; exit 1 }"
    )
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0:
        raise RuntimeError("PowerShell %s 失败: %s"
                           % (mode_name, (r.stderr or r.stdout).strip()))
    out = r.stdout.strip()
    if not out:
        raise RuntimeError("PowerShell %s 返回空结果 (stderr: %s)"
                           % (mode_name, r.stderr.strip() or "(无)"))
    try:
        return bytes.fromhex(out)
    except ValueError:
        raise RuntimeError("PowerShell %s 返回非法 hex 输出: %r"
                           % (mode_name, out[:80]))


# ─── BND4 解析 ─────────────────────────────────────────────────────────

def parse_bnd4_entries(data: bytes):
    """解析 BND4 entry table"""
    if data[:4] != b"BND4":
        return None
    entry_count = struct.unpack_from("<I", data, 0x0C)[0]
    entries = []
    name_list_off = 0x1C0
    for i in range(entry_count):
        entry_off = 0x40 + i * 32
        if entry_off + 32 > len(data):
            break
        e_off = struct.unpack_from("<I", data, entry_off + 16)[0]
        e_sz = struct.unpack_from("<I", data, entry_off + 20)[0]
        name_off = name_list_off + i * 26
        if name_off + 26 <= len(data):
            name_raw = data[name_off : name_off + 26]
            name = name_raw.decode("utf-16-le", errors="replace").rstrip("\x00")
        else:
            name = "USER_DATA_%03d" % i
        entries.append({"id": i, "name": name, "offset": e_off, "size": e_sz})
    return entries


def find_user_data_010(entries):
    """在 entry 列表中找到 USER_DATA_010（第 11 个 entry，index 10）"""
    if not entries:
        return None
    # USER_DATA_010 通常是第 11 个 entry（index 10）；优先按 index 取，
    # 避免 name 解析错位时 "010" 误匹配（如 Nightreign 的 TA010）
    if len(entries) > 10:
        return entries[10]
    # fallback: name 含 USER_DATA010
    for e in entries:
        if "USER_DATA010" in e["name"]:
            return e
    return None


# ─── 核心：提取 SteamID ───────────────────────────────────────────────

def extract_steam_id(sl2_path: Path, config: dict):
    """从存档中提取绑定的 SteamID（十进制）。

    `bind_mode == "folder"`（DS2/DSR）时存档内部不绑定 SteamID，
    识别靠文件夹名（STEAMID3/十六进制），直接返回 None。
    """
    if config.get("bind_mode", "internal") == "folder":
        return None
    try:
        with open(sl2_path, "rb") as f:
            data = f.read()
    except (FileNotFoundError, OSError):
        return None

    entries = parse_bnd4_entries(data)
    entry = find_user_data_010(entries)
    if not entry or entry["size"] == 0:
        return None

    enc = data[entry["offset"] : entry["offset"] + entry["size"]]
    off = config["steam_id_offset"]
    stype = config.get("struct_type", "md5_iv_ct")
    if stype == "plain":
        # 明文模式（ER/Sekiro）：直接读原始字节
        buf = enc
    elif stype == "iv_ct":
        # [iv(16)|ct]，IV 在前 16 字节（Nightreign）
        if len(enc) < 16:
            return None
        iv = enc[0:16]
        ciphertext = enc[16:]
        ciphertext = ciphertext[:len(ciphertext) - len(ciphertext) % 16]
        key = bytes.fromhex(config["aes_key_hex"])
        try:
            buf = aes_decrypt(ciphertext, iv, key)
        except Exception:
            return None
    else:  # md5_iv_ct（DS3/DS2/DSR）：[md5(16)|iv(16)|ct]
        if len(enc) < 32:
            return None
        iv = enc[16:32]
        ciphertext = enc[32:]
        ciphertext = ciphertext[:len(ciphertext) - len(ciphertext) % 16]
        key = bytes.fromhex(config["aes_key_hex"])
        try:
            buf = aes_decrypt(ciphertext, iv, key)
        except Exception:
            return None
    if len(buf) < off + 8:
        return None

    return struct.unpack_from("<Q", buf, off)[0]


# ─── 核心：修改 SteamID ───────────────────────────────────────────────

def patch_steam_id(src_path: Path, new_steam_id: int, output_path: Path, config: dict) -> bool:
    """修改存档中的 SteamID，输出新文件。

    `bind_mode == "folder"`（DS2/DSR）：存档内部不绑定 SteamID，迁移靠文件夹名，
    本函数走**纯文件复制**（不解密、不改字节），目标 SteamID 由文件夹名决定。
    """
    if config.get("bind_mode", "internal") == "folder":
        try:
            shutil.copy2(src_path, output_path)
        except OSError as e:
            print("    [!] 复制失败: %s" % e)
            return False
        print("    该游戏不内部绑定 SteamID（靠文件夹名识别账号），已直接复制，未修改存档内部")
        return True

    try:
        with open(src_path, "rb") as f:
            data = bytearray(f.read())
    except (FileNotFoundError, OSError):
        print("    [!] 文件不存在或无法读取")
        return False

    entries = parse_bnd4_entries(data)
    entry = find_user_data_010(entries)
    if not entry or entry["size"] == 0:
        print("    [!] 未找到 USER_DATA_010")
        return False

    enc = bytes(data[entry["offset"] : entry["offset"] + entry["size"]])
    off = config["steam_id_offset"]
    stype = config.get("struct_type", "md5_iv_ct")
    if stype == "plain":
        # 明文模式（ER/Sekiro）：直接改原始字节，保留原 checksum
        if len(enc) < off + 8:
            print("    [!] USER_DATA_010 数据过短")
            return False
        plain = bytearray(enc)
        old_sid = struct.unpack_from("<Q", plain, off)[0]
        print("    旧 SteamID: %s" % old_sid)
        print("    新 SteamID: %s" % new_steam_id)
        struct.pack_into("<Q", plain, off, new_steam_id)
        new_enc = bytes(plain)
    elif stype == "iv_ct":
        # [iv(16)|ct]，IV 在前 16 字节（Nightreign）
        if len(enc) < 16:
            print("    [!] 加密数据过短")
            return False
        iv = enc[0:16]
        ciphertext = enc[16:]
        original_ct_len = len(ciphertext)
        ciphertext = ciphertext[:original_ct_len - original_ct_len % 16]
        key = bytes.fromhex(config["aes_key_hex"])
        try:
            plain = bytearray(aes_decrypt(ciphertext, iv, key))
        except Exception as e:
            print("    [!] 解密失败: %s" % e)
            return False
        old_sid = struct.unpack_from("<Q", plain, off)[0]
        print("    旧 SteamID: %s" % old_sid)
        print("    新 SteamID: %s" % new_steam_id)
        struct.pack_into("<Q", plain, off, new_steam_id)
        try:
            new_cipher = aes_encrypt(bytes(plain), iv, key)
        except Exception as e:
            print("    [!] 加密失败: %s" % e)
            return False
        # 保留原 IV（前 16）+ trailer
        trailer = enc[16 + original_ct_len - original_ct_len % 16:16 + original_ct_len]
        new_enc = iv + new_cipher + trailer
    else:  # md5_iv_ct（DS3/DS2/DSR）：[md5(16)|iv(16)|ct]
        if len(enc) < 32:
            print("    [!] 加密数据过短")
            return False
        iv = enc[16:32]
        ciphertext = enc[32:]
        original_ct_len = len(ciphertext)
        ciphertext = ciphertext[:original_ct_len - original_ct_len % 16]
        key = bytes.fromhex(config["aes_key_hex"])
        try:
            plain = bytearray(aes_decrypt(ciphertext, iv, key))
        except Exception as e:
            print("    [!] 解密失败: %s" % e)
            return False
        old_sid = struct.unpack_from("<Q", plain, off)[0]
        print("    旧 SteamID: %s" % old_sid)
        print("    新 SteamID: %s" % new_steam_id)
        struct.pack_into("<Q", plain, off, new_steam_id)
        try:
            new_cipher = aes_encrypt(bytes(plain), iv, key)
        except Exception as e:
            print("    [!] 加密失败: %s" % e)
            return False
        # 保留原 MD5 + trailer
        trailer = enc[32 + original_ct_len - original_ct_len % 16:32 + original_ct_len]
        new_enc = enc[:16] + iv + new_cipher + trailer

    if len(new_enc) > len(enc):
        new_enc = new_enc[: len(enc)]
    elif len(new_enc) < len(enc):
        new_enc = new_enc + b"\x00" * (len(enc) - len(new_enc))

    data[entry["offset"] : entry["offset"] + len(new_enc)] = new_enc

    try:
        with open(output_path, "wb") as f:
            f.write(data)
    except OSError as e:
        print("    [!] 写入失败: %s" % e)
        return False
    return True


def parse_folder_name_steamid(name):
    """从存档文件夹名解析 SteamID，自动探测进制。

    FromSoftware 各游戏的存档文件夹命名进制不同：
      - DS2 / DS3 : 十六进制 SteamID64 (前缀 "0110001")
      - ER / Sekiro: 十进制 SteamID64   (前缀 "7656119")
    含字母 a-f 的文件夹名必为十六进制；纯数字按前缀判断；兜底十六进制。
    """
    if len(name) < 8:
        return None
    if any(c in "abcdefABCDEF" for c in name):
        return int(name, 16)
    if name.startswith("7656119"):
        return int(name, 10)
    if name.startswith("01100001"):
        return int(name, 16)
    # 纯数字且非 SteamID64 前缀：当作 account_id（DSR 文件夹名=account_id 十进制）
    if name.isdigit():
        return int(name, 10) + 0x0110000100000000
    try:
        return int(name, 16)
    except ValueError:
        return None


def is_valid_save_folder_name(name):
    return len(name) >= 8 and all(c in '0123456789abcdefABCDEF' for c in name)


# ─── 扫描存档 ──────────────────────────────────────────────────────────

def scan_save_folders(config: dict):
    """扫描游戏的存档目录"""
    appdata = Path(os.environ.get("APPDATA", "")) / config["appdata_dir"]
    if not appdata.exists():
        return []
    folders = []
    for entry in sorted(appdata.iterdir(), key=lambda p: p.name):
        if entry.is_dir() and is_valid_save_folder_name(entry.name):
            if list(entry.glob(config["file_ext"])):
                folders.append((entry, entry.name))
    return folders


def manual_select_save_file(config: dict):
    """手动指定存档文件路径"""
    print("\n  请输入存档文件的完整路径 (.sl2 或 .co2)")
    print("  (例如: C:\\Users\\xxx\\AppData\\Roaming\\%s\\xxxxx\\DS30000.sl2)" % config["appdata_dir"])
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

def select_game():
    """选择游戏"""
    print("\n" + "=" * 60)
    print("  FS Save Migrator — FromSoftware 存档通用迁移工具 v2")
    print("=" * 60)
    print("\n支持的遊戲:")
    for k, v in GAME_CONFIGS.items():
        print("  [%s] %s  (%s)" % (k, v["name"], v["notes"]))
    print("  [q] 退出")
    while True:
        choice = input("\n请选择游戏: ").strip()
        if choice.lower() == "q":
            sys.exit(0)
        if choice in GAME_CONFIGS:
            return choice, GAME_CONFIGS[choice]
        print("  无效选择")


def select_folders(folders: list, config: dict):
    """选择源和目标存档"""
    if not folders:
        print("\n  [!] 在 %%APPDATA%%\\%s\\ 下未找到存档文件夹。" % config["appdata_dir"])
        print("  请确认已运行过该游戏（至少一次以生成存档）。")
        return -1, -1

    print("\n  找到 %d 个存档文件夹:\n" % len(folders))
    for i, (path, hex_str) in enumerate(folders):
        sl2_files = list(path.glob(config["file_ext"]))
        sid_info = ""
        if sl2_files:
            sid = extract_steam_id(sl2_files[0], config)
            if sid:
                sid_info = "  [存档内 SteamID: %s]" % sid
        folder_sid = parse_folder_name_steamid(path.name)
        print("  [%d] %s  (文件夹名->SteamID: %s)%s"
              % (i, path.name, folder_sid if folder_sid else "?", sid_info))

    print("\n  --- 选择源存档（来源） ---")
    while True:
        try:
            si = int(input("  源存档编号: "))
            if 0 <= si < len(folders):
                break
        except ValueError:
            pass
        print("  请输入 0-%d" % (len(folders) - 1))

    print("\n  --- 选择目标存档（要覆盖/替换的存档） ---")
    while True:
        try:
            di = int(input("  目标存档编号: "))
            if 0 <= di < len(folders):
                break
        except ValueError:
            pass
        print("  请输入 0-%d" % (len(folders) - 1))

    return si, di


# ─── 选择存档（源/目标通用）──────────────────────────────────────────

def choose_save(folders, config, role):
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
            for i, (path, hex_str) in enumerate(folders):
                sl2_files = list(path.glob(config["file_ext"]))
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
            sl2 = list(p.glob(config["file_ext"]))
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

def main():
    game_key, config = select_game()

    print("\n扫描 %%APPDATA%%\\%s\\ ..." % config["appdata_dir"])
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
    if config.get("bind_mode", "internal") == "folder":
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
        new_sid = src_target_sid
        output_dir = src_path
        desc = "将 %s 的存档迁移到 %s" % (dst_path.name, src_path.name)

    print("\n  ⚠️  即将执行: %s" % desc)
    if config.get("bind_mode", "internal") == "folder":
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


if __name__ == "__main__":
    main()
