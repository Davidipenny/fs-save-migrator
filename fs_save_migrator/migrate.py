"""核心迁移逻辑：SteamID 提取 / 修改 / 文件夹名进制 / 存档目录扫描
==================================================================

数据流：
  .sl2 = BND4 容器
    → parse_bnd4_entries → find_user_data_010 (index 10)
    → 按 struct_type 解封装/解密 → 改 off 处 8 字节 → 重新封装/加密
    → 保留原 MD5/IV/trailer → 写新文件

patch_steam_id 不修改源文件；folder 模式（DS2/DSR）走纯复制。
"""
import os
import shutil
import struct
from pathlib import Path

from .bnd4 import decrypt_user_data_entry, find_user_data_010, parse_bnd4_entries
from .crypto import aes_decrypt, aes_encrypt
from .games import STRUCT_HEADER_LEN, GameConfig

# ─── 核心：提取 SteamID ───────────────────────────────────────────────

def extract_steam_id(sl2_path: Path, config: GameConfig) -> int | None:
    """从存档中提取绑定的 SteamID（十进制）。

    `bind_mode == "folder"`（DS2/DSR）时存档内部不绑定 SteamID，
    识别靠文件夹名（STEAMID3/十六进制），直接返回 None。
    """
    if config.bind_mode == "folder":
        return None
    try:
        with open(sl2_path, "rb") as f:
            data = f.read()
    except (FileNotFoundError, OSError):
        return None

    entries = parse_bnd4_entries(data)
    entry = find_user_data_010(entries)
    if not entry or entry.size == 0:
        return None

    key = bytes.fromhex(config.aes_key_hex)
    buf = decrypt_user_data_entry(data, entry, key, config.struct_type)
    if buf is None:
        return None
    off = config.steam_id_offset
    if len(buf) < off + 8:
        return None

    return struct.unpack_from("<Q", buf, off)[0]


# ─── 核心：修改 SteamID ───────────────────────────────────────────────

def patch_steam_id(src_path: Path, new_steam_id: int,
                   output_path: Path, config: GameConfig) -> bool:
    """修改存档中的 SteamID，输出新文件。

    `bind_mode == "folder"`（DS2/DSR）：存档内部不绑定 SteamID，迁移靠文件夹名，
    本函数走**纯文件复制**（不解密、不改字节），目标 SteamID 由文件夹名决定。
    """
    if config.bind_mode == "folder":
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
    if not entry or entry.size == 0:
        print("    [!] 未找到 USER_DATA_010")
        return False

    enc = bytes(data[entry.offset : entry.offset + entry.size])
    off = config.steam_id_offset
    stype = config.struct_type
    head = STRUCT_HEADER_LEN[stype]

    if stype == "plain":
        # 明文模式（ER/Sekiro）：直接改原始字节，保留原 checksum
        if len(enc) < off + 8:
            print("    [!] USER_DATA_010 数据过短")
            return False
        plain = bytearray(enc)
    else:
        # md5_iv_ct / iv_ct：head 之前是 [md5 +] iv，其后是密文
        iv = enc[head - 16 : head]
        ciphertext = enc[head:]
        original_ct_len = len(ciphertext)
        ciphertext = ciphertext[:original_ct_len - original_ct_len % 16]
        key = bytes.fromhex(config.aes_key_hex)
        try:
            plain = bytearray(aes_decrypt(ciphertext, iv, key))
        except Exception as e:
            print("    [!] 解密失败: %s" % e)
            return False
        if len(plain) < off + 8:
            print("    [!] 解密后数据过短")
            return False

    old_sid = struct.unpack_from("<Q", plain, off)[0]
    print("    旧 SteamID: %s" % old_sid)
    print("    新 SteamID: %s" % new_steam_id)
    struct.pack_into("<Q", plain, off, new_steam_id)

    if stype == "plain":
        new_enc = bytes(plain)
    else:
        try:
            new_cipher = aes_encrypt(bytes(plain), iv, key)
        except Exception as e:
            print("    [!] 加密失败: %s" % e)
            return False
        # 保留原头部（md5 + 原 IV）+ trailer
        trailer = enc[head + len(ciphertext) : head + original_ct_len]
        new_enc = enc[:head] + new_cipher + trailer

    if len(new_enc) > len(enc):
        new_enc = new_enc[: len(enc)]
    elif len(new_enc) < len(enc):
        new_enc = new_enc + b"\x00" * (len(enc) - len(new_enc))

    data[entry.offset : entry.offset + len(new_enc)] = new_enc

    try:
        with open(output_path, "wb") as f:
            f.write(data)
    except OSError as e:
        print("    [!] 写入失败: %s" % e)
        return False
    return True


# ─── 文件夹名进制探测 ─────────────────────────────────────────────────

def parse_folder_name_steamid(name: str) -> int | None:
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


def is_valid_save_folder_name(name: str) -> bool:
    return len(name) >= 8 and all(c in '0123456789abcdefABCDEF' for c in name)


# ─── 扫描存档 ──────────────────────────────────────────────────────────

def scan_save_folders(config: GameConfig) -> list[tuple[Path, str]]:
    """扫描游戏的存档目录"""
    appdata = Path(os.environ.get("APPDATA", "")) / config.appdata_dir
    if not appdata.exists():
        return []
    folders: list[tuple[Path, str]] = []
    for entry in sorted(appdata.iterdir(), key=lambda p: p.name):
        if entry.is_dir() and is_valid_save_folder_name(entry.name):
            if list(entry.glob(config.file_ext)):
                folders.append((entry, entry.name))
    return folders
