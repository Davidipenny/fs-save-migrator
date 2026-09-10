"""核心迁移逻辑测试：extract / patch 闭环、进制探测、目录扫描
==============================================================

三种 struct_type 的闭环全部用合成存档验证（不依赖真实存档）；
真实存档回归见 test_real_archives.py。
"""
import hashlib

from fs_save_migrator import (
    extract_steam_id,
    is_valid_save_folder_name,
    parse_folder_name_steamid,
    patch_steam_id,
    scan_save_folders,
)
from tests.conftest import make_synthetic_save, synthetic_config

ALL_STRUCT_TYPES = [
    ("md5_iv_ct", 0x08),  # DS3 / DS2 / DSR
    ("iv_ct", 0x08),      # Nightreign
    ("plain", 0x14),      # ER（Sekiro @0x34 同理）
]


# ─── extract + patch 闭环（internal 模式，三种结构）──────────────────

def test_extract_and_patch_round_trip(synthetic_save_factory, tmp_path):
    for struct_type, off in ALL_STRUCT_TYPES:
        p, config, sid = synthetic_save_factory(struct_type, off)
        assert extract_steam_id(p, config) == sid, struct_type

        out = tmp_path / ("out_%s.sl2" % struct_type)
        assert patch_steam_id(p, sid + 1, out, config), struct_type

        # 输出文件大小一致、SteamID 已改、源文件未被修改
        assert out.stat().st_size == p.stat().st_size, struct_type
        assert extract_steam_id(out, config) == sid + 1, struct_type
        assert extract_steam_id(p, config) == sid, struct_type


def test_patch_keeps_other_bytes_intact(synthetic_save_factory, tmp_path):
    """internal patch 只应改 USER_DATA_010 内 SteamID 8 字节窗口；
    容器其余部分逐字节一致（plain 结构不重加密，可直接全文比对）。"""
    p, config, sid = synthetic_save_factory("plain", 0x14)
    out = tmp_path / "out_plain.sl2"
    assert patch_steam_id(p, sid + 1, out, config)

    src, dst = p.read_bytes(), out.read_bytes()
    diff = [i for i in range(len(src)) if src[i] != dst[i]]
    entry10_off = 0x300 + 10 * 32  # 前 10 个 entry 各 32 字节
    window = set(range(entry10_off + 0x14, entry10_off + 0x14 + 8))
    assert diff and set(diff) <= window  # sid+1 小端通常仅最低字节变


def test_folder_mode_patch_is_pure_copy(tmp_path):
    """folder 模式（DS2/DSR）：patch = 字节级一致纯复制。"""
    src = tmp_path / "src.sl2"
    payload = b"\xEE" * 1024
    src.write_bytes(payload)
    out = tmp_path / "out.sl2"

    assert patch_steam_id(src, 123456789, out, synthetic_config("md5_iv_ct", 0x08, "folder"))
    assert out.read_bytes() == payload
    assert hashlib.md5(out.read_bytes()).hexdigest() == hashlib.md5(payload).hexdigest()


def test_folder_mode_extract_returns_none(synthetic_save_factory):
    p, config, _ = synthetic_save_factory("md5_iv_ct", 0x08)
    config = synthetic_config("md5_iv_ct", 0x08, "folder")
    assert extract_steam_id(p, config) is None


# ─── 错误处理 ─────────────────────────────────────────────────────────

def test_extract_nonexistent_returns_none(tmp_path):
    config = synthetic_config("md5_iv_ct", 0x08)
    assert extract_steam_id(tmp_path / "nope.sl2", config) is None


def test_extract_empty_file_returns_none(tmp_path):
    p = tmp_path / "empty.sl2"
    p.write_bytes(b"")
    assert extract_steam_id(p, synthetic_config("md5_iv_ct", 0x08)) is None


def test_extract_invalid_bnd4_returns_none(tmp_path):
    p = tmp_path / "invalid.sl2"
    p.write_bytes(b"XXXX" + b"\x00" * 100)
    assert extract_steam_id(p, synthetic_config("md5_iv_ct", 0x08)) is None


def test_extract_wrong_key_no_crash(tmp_path):
    """NoPadding 下错钥解密不抛异常、不崩溃（乱码 sid 或 None 均可，
    与原版脚本行为一致）。"""
    from fs_save_migrator import GameConfig
    data = make_synthetic_save("iv_ct", 0x08)
    p = tmp_path / "wrong_key.sl2"
    p.write_bytes(data)
    bad = GameConfig(
        name="bad", appdata_dir="x", file_ext="*.sl2",
        aes_key_hex="FFFF0000FFFF0000FFFF0000FFFF0000",
        struct_type="iv_ct", steam_id_offset=0x08,
        user_data_id=10, bind_mode="internal",
    )
    sid = extract_steam_id(p, bad)
    assert sid is None or isinstance(sid, int)


# ─── 文件夹名进制探测 ─────────────────────────────────────────────────

RADIX_CASES = [
    ("0110000100000666", 76561197960267366),   # DS3 hex 纯数字
    ("0110000167dacdf4", 76561199702658548),   # DS2/DS3 hex 含字母
    ("0110000173b6c269", 76561199901622889),   # DS3 hex 含字母
    ("76561199702658548", 76561199702658548),  # ER/Sekiro/NR 十进制
    ("76561197960265728", 76561197960265728),  # 十进制基准
    ("1742392820", 76561199702658548),         # DSR account_id 十进制 → +base
    ("short", None),                           # 过短
    ("", None),
]


def test_parse_folder_name_steamid():
    for name, want in RADIX_CASES:
        assert parse_folder_name_steamid(name) == want, name


def test_is_valid_save_folder_name():
    assert is_valid_save_folder_name("0110000167dacdf4")
    assert is_valid_save_folder_name("76561199702658548")
    assert not is_valid_save_folder_name("short")
    assert not is_valid_save_folder_name("has_underscore")


# ─── 存档目录扫描（monkeypatch APPDATA，跨平台）──────────────────────

def test_scan_save_folders(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    config = synthetic_config("md5_iv_ct", 0x08)

    # 空 / 无该游戏目录 → []
    assert scan_save_folders(config) == []

    game_dir = tmp_path / "SyntheticTest"
    (game_dir / "0110000167dacdf4").mkdir(parents=True)
    (game_dir / "0110000167dacdf4" / "SAVE0000.sl2").write_bytes(b"\x00")
    (game_dir / "not_a_steamid").mkdir()          # 无效文件夹名 → 忽略
    (game_dir / "0110000173b6c269").mkdir()       # 有效名但无 .sl2 → 忽略

    folders = scan_save_folders(config)
    assert folders == [(game_dir / "0110000167dacdf4", "0110000167dacdf4")]
