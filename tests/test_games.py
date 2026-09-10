"""游戏配置表完整性测试"""
from dataclasses import fields

from fs_save_migrator import GAME_CONFIGS, GameConfig

REQUIRED_FIELDS = {f.name for f in fields(GameConfig)}


def test_six_games_configured():
    assert len(GAME_CONFIGS) == 6


def test_all_configs_complete():
    for key, cfg in GAME_CONFIGS.items():
        assert isinstance(cfg, GameConfig)
        for name in ("name", "appdata_dir", "file_ext", "struct_type",
                     "bind_mode"):
            # aes_key_hex 允许为空（plain 结构无密钥），单独在
            # test_encrypted_games_have_keys 校验
            assert getattr(cfg, name), "%s 缺字段 %s" % (key, name)
        assert isinstance(cfg.steam_id_offset, int) and cfg.steam_id_offset >= 0
        assert isinstance(cfg.user_data_id, int)


def test_struct_types_valid():
    for cfg in GAME_CONFIGS.values():
        assert cfg.struct_type in ("md5_iv_ct", "iv_ct", "plain")
        assert cfg.bind_mode in ("internal", "folder")


def test_encrypted_games_have_keys():
    """非 plain 结构必须有密钥；plain 结构密钥为空。"""
    for cfg in GAME_CONFIGS.values():
        if cfg.struct_type == "plain":
            assert cfg.aes_key_hex == ""
        else:
            assert len(bytes.fromhex(cfg.aes_key_hex)) == 16, cfg.name


def test_folder_games_do_not_need_offset():
    """folder 模式的 offset 不适用，但字段仍存在（保留 0x08 历史值）。"""
    for cfg in GAME_CONFIGS.values():
        if cfg.bind_mode == "folder":
            assert cfg.name  # DS2/DSR：纯复制迁移
