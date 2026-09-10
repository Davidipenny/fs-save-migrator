"""pytest 共享夹具与工具
========================

- 把项目根（fs-save-migrator/）加入 sys.path，未 pip install 也能跑测试
- build_bnd4：按 parse_bnd4_entries 的布局假设反向构造合成 BND4 容器，
  使加解密 / patch 闭环测试不依赖真实存档
"""
import struct
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fs_save_migrator import GameConfig  # noqa: E402

# 测试专用 AES-128 密钥（与真实游戏密钥无关）
TEST_KEY_HEX = "00112233445566778899AABBCCDDEEFF"
TEST_KEY = bytes.fromhex(TEST_KEY_HEX)
TEST_IV = bytes.fromhex("0102030405060708090A0B0C0D0E0F10")
TEST_SID = 76561199702658548  # 0x0110000167DACDF4


def make_user_data_010_plain(sid: int, offset: int, total_len: int = 0x2E0) -> bytes:
    """构造 plain 结构（ER/Sekiro）的 USER_DATA_010 数据，sid 写在 offset 处。"""
    buf = bytearray(b"\xAA" * total_len)
    struct.pack_into("<Q", buf, offset, sid)
    return bytes(buf)


def make_user_data_010_encrypted(sid: int, offset: int, struct_type: str,
                                 total_len: int = 0x2E0) -> bytes:
    """构造加密结构（md5_iv_ct / iv_ct）的 USER_DATA_010 数据。

    plain 长度取 16 倍数（0x2E0）——真实存档明文本就 16 字节对齐、
    无 PKCS7 填充（NoPadding，见 crypto.py 模块注释）。
    """
    from fs_save_migrator.crypto import aes_encrypt

    plain = bytearray(b"\xBB" * total_len)
    struct.pack_into("<Q", plain, offset, sid)
    iv, ct = TEST_IV, aes_encrypt(bytes(plain), TEST_IV, TEST_KEY)
    if struct_type == "iv_ct":           # [iv | ct]
        return iv + ct
    # md5_iv_ct: [md5 | iv | ct]（md5 内容不影响本工具，占位即可）
    return b"\x11" * 16 + iv + ct


def build_bnd4(entry_payloads: list[bytes]) -> bytes:
    """反向构造 BND4 容器，布局对齐 parse_bnd4_entries 的解析假设：

      - magic "BND4" @0x00，entry_count @0x0C
      - entry table @0x40 起，每条目 32 字节：offset@+16、size@+20
      - name list @0x1C0，每名 26 字节 utf-16-le
      - 条目数据区从 0x300 起（与真实 DS3 的 entry0 offset=0x300 一致）
    """
    n = len(entry_payloads)
    name_list_off = 0x1C0
    data_start = 0x300

    buf = bytearray(data_start)
    buf[0:4] = b"BND4"
    struct.pack_into("<I", buf, 0x0C, n)

    # name list（0x1C0 + n*26 ≤ 0x300 需 n ≤ 12）
    assert name_list_off + n * 26 <= data_start, "entry 过多会覆盖数据区"
    for i in range(n):
        name = ("USER_DATA%03d" % i).encode("utf-16-le")
        off = name_list_off + i * 26
        buf[off : off + len(name)] = name

    # entry table + 顺序追加条目数据
    cur = data_start
    for i, payload in enumerate(entry_payloads):
        entry_off = 0x40 + i * 32
        struct.pack_into("<I", buf, entry_off + 16, cur)
        struct.pack_into("<I", buf, entry_off + 20, len(payload))
        buf.extend(payload)
        cur += len(payload)
    return bytes(buf)


def make_synthetic_save(struct_type: str, sid_offset: int,
                        sid: int = TEST_SID) -> bytes:
    """构造 12-entry 合成存档：entry 0-9 占位、entry 10 为目标结构、entry 11 占位。"""
    if struct_type == "plain":
        entry10 = make_user_data_010_plain(sid, sid_offset)
    else:
        entry10 = make_user_data_010_encrypted(sid, sid_offset, struct_type)
    payloads = [b"\xCC" * 32] * 10 + [entry10] + [b"\xDD" * 48]
    return build_bnd4(payloads)


def synthetic_config(struct_type: str, sid_offset: int,
                     bind_mode: str = "internal") -> GameConfig:
    """构造测试用 GameConfig（测试密钥，plain 结构密钥为空）。"""
    return GameConfig(
        name="Synthetic Test Game",
        appdata_dir="SyntheticTest",
        file_ext="*.sl2",
        aes_key_hex="" if struct_type == "plain" else TEST_KEY_HEX,
        struct_type=struct_type,
        steam_id_offset=sid_offset,
        user_data_id=10,
        bind_mode=bind_mode,
        notes="synthetic",
    )


@pytest.fixture
def synthetic_save_factory(tmp_path: Path):
    """返回 (写合成存档到临时文件) 的工厂，产出 (path, config, sid)。"""
    def _make(struct_type: str, sid_offset: int, sid: int = TEST_SID):
        config = synthetic_config(struct_type, sid_offset)
        data = make_synthetic_save(struct_type, sid_offset, sid)
        p = tmp_path / ("syn_%s.sl2" % struct_type)
        p.write_bytes(data)
        return p, config, sid
    return _make
