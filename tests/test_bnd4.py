"""BND4 解析 + USER_DATA 条目解封装测试（合成容器，不依赖真实存档）"""
from fs_save_migrator import decrypt_user_data_entry, find_user_data_010, parse_bnd4_entries
from tests.conftest import (
    TEST_KEY,
    TEST_SID,
    build_bnd4,
    make_synthetic_save,
    make_user_data_010_plain,
)


def _make_12_entry_container() -> bytes:
    return build_bnd4([b"\xCC" * 32] * 12)


def test_parse_bnd4_entries_count_and_names():
    entries = parse_bnd4_entries(_make_12_entry_container())
    assert entries is not None and len(entries) == 12
    assert "USER_DATA000" in entries[0].name
    assert "USER_DATA010" in entries[10].name


def test_parse_bnd4_entry0_offset():
    entries = parse_bnd4_entries(_make_12_entry_container())
    assert entries[0].offset == 0x300  # 与真实 DS3 布局一致


def test_parse_bnd4_invalid_magic_returns_none():
    assert parse_bnd4_entries(b"XXXX" + b"\x00" * 100) is None
    assert parse_bnd4_entries(b"") is None


def test_find_user_data_010():
    entries = parse_bnd4_entries(_make_12_entry_container())
    entry = find_user_data_010(entries)
    assert entry is not None and entry.id == 10
    assert find_user_data_010(None) is None
    assert find_user_data_010([]) is None


def test_find_user_data_010_fallback_by_name():
    """entry 不足 11 个时按名字回退匹配。"""
    entries = parse_bnd4_entries(build_bnd4([b"\x00" * 16]))
    assert len(entries) == 1
    assert find_user_data_010(entries) is None  # 只有 USER_DATA000，无 010


# ─── decrypt_user_data_entry：三种 struct_type ────────────────────────

def test_decrypt_entry_plain():
    data = make_synthetic_save("plain", 0x14)
    entry = find_user_data_010(parse_bnd4_entries(data))
    plain = decrypt_user_data_entry(data, entry, b"", "plain")
    assert plain == make_user_data_010_plain(TEST_SID, 0x14)


def test_decrypt_entry_md5_iv_ct():
    import struct
    data = make_synthetic_save("md5_iv_ct", 0x08)
    entry = find_user_data_010(parse_bnd4_entries(data))
    plain = decrypt_user_data_entry(data, entry, TEST_KEY, "md5_iv_ct")
    assert struct.unpack_from("<Q", plain, 0x08)[0] == TEST_SID
    assert plain[:0x08] == b"\xBB" * 8  # 构造时的哨兵字节


def test_decrypt_entry_iv_ct():
    import struct
    data = make_synthetic_save("iv_ct", 0x08)
    entry = find_user_data_010(parse_bnd4_entries(data))
    plain = decrypt_user_data_entry(data, entry, TEST_KEY, "iv_ct")
    assert struct.unpack_from("<Q", plain, 0x08)[0] == TEST_SID


def test_decrypt_entry_wrong_key_no_crash():
    """NoPadding 下错钥解密不抛异常：要么 None（异常路径），要么乱码明文
    （与原版脚本在 cryptography 49 下的行为一致）。"""
    data = make_synthetic_save("iv_ct", 0x08)
    entry = find_user_data_010(parse_bnd4_entries(data))
    result = decrypt_user_data_entry(data, entry, b"\x00" * 16, "iv_ct")
    assert result is None or isinstance(result, bytes)


def test_decrypt_entry_too_short_returns_none():
    from fs_save_migrator import Bnd4Entry
    entry = Bnd4Entry(id=10, name="USER_DATA010", offset=0, size=8)
    assert decrypt_user_data_entry(b"BND4" + b"\x00" * 12, entry, TEST_KEY, "iv_ct") is None
