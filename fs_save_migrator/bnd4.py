"""BND4 容器解析与 USER_DATA 条目解封装
========================================

.sl2 = BND4 容器：
  Header(0x00-0x3F) → Entry Table(0x40 起, 每条目 32 字节:
  unk(16)+offset(4)+size(4)+unk(8)) → 条目数据区

USER_DATA_010（第 11 个 entry，index 10）含全局信息 + SteamID。
"""
import struct
from dataclasses import dataclass

from .crypto import aes_decrypt


@dataclass(frozen=True)
class Bnd4Entry:
    """BND4 entry table 中的一条目。"""

    id: int
    name: str
    offset: int
    size: int


# ─── BND4 解析 ─────────────────────────────────────────────────────────

def parse_bnd4_entries(data: bytes | bytearray) -> list[Bnd4Entry] | None:
    """解析 BND4 entry table；magic 不符返回 None。"""
    if data[:4] != b"BND4":
        return None
    entry_count = struct.unpack_from("<I", data, 0x0C)[0]
    entries: list[Bnd4Entry] = []
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
        entries.append(Bnd4Entry(id=i, name=name, offset=e_off, size=e_sz))
    return entries


def find_user_data_010(entries: list[Bnd4Entry] | None) -> Bnd4Entry | None:
    """在 entry 列表中找到 USER_DATA_010（第 11 个 entry，index 10）"""
    if not entries:
        return None
    # USER_DATA_010 通常是第 11 个 entry（index 10）；优先按 index 取，
    # 避免 name 解析错位时 "010" 误匹配（如 Nightreign 的 TA010）
    if len(entries) > 10:
        return entries[10]
    # fallback: name 含 USER_DATA010
    for e in entries:
        if "USER_DATA010" in e.name:
            return e
    return None


# ─── USER_DATA 条目解封装（按 struct_type 三分支）────────────────────

def decrypt_user_data_entry(data: bytes | bytearray, entry: Bnd4Entry,
                            key: bytes, struct_type: str) -> bytes | None:
    """按 struct_type 解封装单个 entry，返回明文字节；失败返回 None。

    三种结构（与 games.STRUCT_HEADER_LEN 一致）：
      - md5_iv_ct : [md5(16) | iv(16) | ct]  → iv=enc[16:32], ct=enc[32:]
      - iv_ct     : [iv(16) | ct]            → iv=enc[0:16],  ct=enc[16:]
      - plain     : 明文直接返回（ER/Sekiro）
    """
    enc = data[entry.offset : entry.offset + entry.size]
    if struct_type == "plain":
        return bytes(enc)
    if struct_type == "iv_ct":            # [iv(16) | ct]（Nightreign）
        iv, ct = enc[0:16], enc[16:]
    else:                                  # md5_iv_ct：[md5(16) | iv(16) | ct]
        iv, ct = enc[16:32], enc[32:]
    if len(iv) < 16:
        return None
    # 16 字节对齐（处理可能的 trailer）
    ct = ct[: len(ct) - len(ct) % 16]
    try:
        return aes_decrypt(ct, iv, key)
    except Exception:
        return None
