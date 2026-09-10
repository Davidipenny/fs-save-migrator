"""CLI 测试：游戏别名、非交互迁移（dry-run/执行/双向）、多根扫描
================================================================

非交互端到端用合成存档 + 真实游戏配置（ER plain / DS2 folder），
不依赖真实存档。
"""
from dataclasses import replace
from pathlib import Path

import pytest

from fs_save_migrator import (
    GAME_CONFIGS,
    GameConfig,
    extract_steam_id,
    get_save_roots,
    scan_save_folders,
)
from fs_save_migrator.cli import GAME_ALIASES, main
from tests.conftest import TEST_SID, make_synthetic_save

# ─── 游戏别名 ─────────────────────────────────────────────────────────

def test_game_aliases_resolve_to_configs():
    for alias in ("ds3", "ds2", "dsr", "er", "sekiro", "nr"):
        assert GAME_ALIASES[alias] in GAME_CONFIGS
    for num in ("1", "2", "3", "4", "5", "6"):
        assert GAME_ALIASES[num] in GAME_CONFIGS


# ─── 用法错误 → 退出码 2 ─────────────────────────────────────────────

def test_src_dst_require_game():
    with pytest.raises(SystemExit) as e:
        main(["--src", "x.sl2", "--dst", "y"])
    assert e.value.code == 2


def test_game_requires_src_dst():
    with pytest.raises(SystemExit) as e:
        main(["--game", "ds3"])
    assert e.value.code == 2


def test_nonexistent_src_path_returns_2(tmp_path, capsys):
    rc = main(["--game", "er", "--src", str(tmp_path / "nope.sl2"),
               "--dst", str(tmp_path)])
    assert rc == 2
    assert "不存在" in capsys.readouterr().out


# ─── dry-run：只打印计划，不写文件 ────────────────────────────────────

def test_dry_run_prints_plan_without_writing(tmp_path, capsys):
    src = tmp_path / "ER0000.sl2"
    src.write_bytes(make_synthetic_save("plain", 0x14))
    dst_dir = tmp_path / "76561199702658549"  # 目标文件夹名 = 新 SteamID
    dst_dir.mkdir()

    rc = main(["--game", "er", "--src", str(src), "--dst", str(dst_dir),
               "--dry-run"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "迁移计划" in out
    assert "76561199702658549" in out
    assert list(dst_dir.iterdir()) == []  # 未写入任何文件


# ─── 非交互执行：internal 模式闭环（真实 ER 配置 + 合成存档）─────────

def test_non_interactive_internal_migration(tmp_path, capsys):
    src = tmp_path / "ER0000.sl2"
    src.write_bytes(make_synthetic_save("plain", 0x14))
    dst_dir = tmp_path / "76561199702658549"
    dst_dir.mkdir()

    rc = main(["--game", "er", "--src", str(src), "--dst", str(dst_dir),
               "--yes"])

    out = capsys.readouterr().out
    assert rc == 0, out
    produced = list(dst_dir.glob("*.sl2"))
    assert len(produced) == 1
    assert extract_steam_id(produced[0], GAME_CONFIGS["4"]) == 76561199702658549
    assert extract_steam_id(src, GAME_CONFIGS["4"]) == TEST_SID  # 源未变


def test_non_interactive_direction_2(tmp_path):
    """方向 2：目标 → 源（把源文件夹的 SteamID 写入目标的存档副本）。"""
    src_dir = tmp_path / "76561199702658548"
    src_dir.mkdir()
    src_file = src_dir / "ER0000.sl2"
    src_file.write_bytes(make_synthetic_save("plain", 0x14))

    dst_dir = tmp_path / "76561199702658549"
    dst_dir.mkdir()
    (dst_dir / "ER0000.sl2").write_bytes(make_synthetic_save("plain", 0x14, sid=42))

    rc = main(["--game", "er", "--src", str(src_dir), "--dst", str(dst_dir),
               "--direction", "2", "--yes"])

    assert rc == 0
    # 目标文件夹里的存档被 patch 成目标自己的 sid（42）后……注意方向 2 的
    # 语义：source=dst 存档，new_sid=源的 sid → 输出写在源文件夹
    produced = src_dir / "ER0000.sl2"
    assert extract_steam_id(produced, GAME_CONFIGS["4"]) == 76561199702658548
    # 源文件夹原存档备份为 .bak
    assert (src_dir / "ER0000.sl2.bak").exists()


# ─── 非交互执行：folder 模式纯复制（真实 DS2 配置）───────────────────

def test_non_interactive_folder_mode_pure_copy(tmp_path):
    payload = b"\xEE" * 512
    src_dir = tmp_path / "0110000167dacdf4"
    src_dir.mkdir()
    (src_dir / "DS2SOFS0000.sl2").write_bytes(payload)
    dst_dir = tmp_path / "0110000100000666"
    dst_dir.mkdir()

    rc = main(["--game", "ds2", "--src", str(src_dir), "--dst", str(dst_dir),
               "--yes"])

    assert rc == 0
    assert (dst_dir / "DS2SOFS0000.sl2").read_bytes() == payload  # 字节级一致


# ─── 多候选根：DSR alt_save_roots 合并扫描 ───────────────────────────

def _dsr_like_config(appdata_dir: str = "FakeDSR") -> GameConfig:
    return replace(GAME_CONFIGS["3"], appdata_dir=appdata_dir,
                   alt_save_roots=("NBGI/FAKE DSR",))


def test_get_save_roots_includes_appdata_and_documents(
        monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("OneDrive", str(tmp_path / "onedrive-env"))
    config = _dsr_like_config()

    roots = get_save_roots(config)

    assert (tmp_path / "appdata" / "FakeDSR") in roots
    assert (tmp_path / "onedrive-env" / "Documents" / "NBGI" / "FAKE DSR") in roots
    assert (Path.home() / "Documents" / "NBGI" / "FAKE DSR") in roots


def test_scan_merges_all_roots(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("OneDrive", str(tmp_path / "onedrive-env"))
    monkeypatch.delenv("HOME", raising=False)  # 避免 linux 下 home 干扰（仅测试关注两个根）
    config = _dsr_like_config()

    a = tmp_path / "appdata" / "FakeDSR" / "0110000167dacdf4"
    a.mkdir(parents=True)
    (a / "DRAKS0005.sl2").write_bytes(b"\x00")
    b = tmp_path / "onedrive-env" / "Documents" / "NBGI" / "FAKE DSR" / "1742392820"
    b.mkdir(parents=True)
    (b / "DRAKS0005.sl2").write_bytes(b"\x00")

    folders = scan_save_folders(config)
    assert {p.name for p, _ in folders} == {"0110000167dacdf4", "1742392820"}
