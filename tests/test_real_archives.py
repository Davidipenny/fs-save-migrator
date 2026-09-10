"""真实存档回归验证（原 test_real_archives.py 的 pytest 版）
============================================================

依赖仓库根 `可用于检验的存档/`（.gitignore 排除，仅本地存在）；
目录或文件缺失时自动 skip（CI / 他人机器照常全绿）。
"""
import hashlib
from pathlib import Path

import pytest

from fs_save_migrator import GAME_CONFIGS, extract_steam_id, patch_steam_id

ROOT = Path(__file__).resolve().parent.parent.parent / "可用于检验的存档"

CASES = [
    ("2", "Darksouls2/0110000167dacdf4/DS2SOFS0000.sl2"),      # folder
    ("3", "DARK SOULS REMASTERED/1742392820/DRAKS0005.sl2"),   # folder
    ("1", "Darksouls3/0110000167dacdf4/DS30000.sl2"),          # internal
]


def _archive(rel: str) -> Path:
    p = ROOT / rel
    if not p.exists():
        pytest.skip("真实存档缺失: %s" % rel)
    return p


pytestmark = pytest.mark.skipif(
    not ROOT.exists(), reason="真实存档目录不存在（仅本地保留，不入库）")


# ─── 用例 1: extract 行为符合 bind_mode 预期 ──────────────────────────

@pytest.mark.parametrize("key,rel", CASES, ids=["ds2", "dsr", "ds3"])
def test_extract_matches_bind_mode(key, rel):
    config = GAME_CONFIGS[key]
    p = _archive(rel)
    sid = extract_steam_id(p, config)
    if config.bind_mode == "folder":
        assert sid is None
    else:
        assert sid is not None and sid > 0


# ─── 用例 2: folder 模式 patch = 字节级一致纯复制 ─────────────────────

@pytest.mark.parametrize("key,rel", CASES[:2], ids=["ds2", "dsr"])
def test_folder_mode_patch_is_pure_copy(key, rel, tmp_path):
    config = GAME_CONFIGS[key]
    p = _archive(rel)
    out = tmp_path / p.name
    assert patch_steam_id(p, 123456789, out, config)
    assert hashlib.md5(out.read_bytes()).hexdigest() \
        == hashlib.md5(p.read_bytes()).hexdigest()
    assert out.stat().st_size == p.stat().st_size


# ─── 用例 3: internal 模式 patch 闭环（DS3）───────────────────────────

def test_ds3_patch_round_trip(tmp_path):
    key, rel = CASES[2]
    config = GAME_CONFIGS[key]
    p = _archive(rel)
    sid = extract_steam_id(p, config)
    assert sid

    out = tmp_path / "out.sl2"
    assert patch_steam_id(p, sid + 1, out, config)
    assert extract_steam_id(out, config) == sid + 1
    assert extract_steam_id(p, config) == sid  # 源文件未被修改


def test_sekiro_and_nightreign_extract():
    """Sekiro/NR 真实存档的 internal 提取（原始验证结论：0x34 / 0x08 命中）。"""
    sekiro = ROOT / "Sekiro/76561199702658548/S0000.sl2"
    nr = ROOT / "Nightreign/76561199702658548/NR0000.sl2"
    if sekiro.exists():
        assert extract_steam_id(sekiro, GAME_CONFIGS["5"]) == 76561199702658548
    if nr.exists():
        assert extract_steam_id(nr, GAME_CONFIGS["6"]) == 76561199702658548


def test_er_co2_backup_extract():
    """ER 黑盒备份 .co2：文件夹名非 SteamID，靠存档内部提取（@0x14 命中）。"""
    co2 = ROOT / "Eldenring/76561199702658548/ER0000.co2"
    if co2.exists():
        assert extract_steam_id(co2, GAME_CONFIGS["4"]) == 76561199702658548
