"""游戏配置表 — 6 款游戏的全部差异收敛于此
==============================================

新增游戏 = 加一条 GameConfig。字段含义：

  - struct_type      : USER_DATA_010 封装结构
      md5_iv_ct : [md5(16) | iv(16) | ct]   （DS3 / DS2 / DSR）
      iv_ct     : [iv(16) | ct]              （Nightreign，无 md5）
      plain     : 明文，不加密（ER / Sekiro，头部带 checksum）
  - bind_mode        : SteamID 绑定方式
      internal  : 存档内部绑定 SteamID，迁移 = patch 内部字节
      folder    : 不内部绑定，靠文件夹名识别账号，迁移 = 纯复制
  - steam_id_offset  : SteamID 在明文内的偏移（小端 uint64）；folder 模式不适用
  - aes_key_hex      : 各游戏密钥不同；空字符串 = plain 结构无密钥
  - alt_save_roots   : %APPDATA% 相应目录之外的候选存档根（相对 Documents/，
                       如 DSR 的 "NBGI/DARK SOULS REMASTERED"），扫描时合并
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class GameConfig:
    """单款游戏的存档格式参数。"""

    name: str
    appdata_dir: str
    file_ext: str
    aes_key_hex: str        # 空字符串 = plain 结构（无密钥）
    struct_type: str        # md5_iv_ct | iv_ct | plain
    steam_id_offset: int    # 明文内偏移；folder 模式不适用
    user_data_id: int       # USER_DATA_xxx 的 entry index（当前恒为 10）
    bind_mode: str          # internal | folder
    notes: str = ""
    alt_save_roots: tuple[str, ...] = field(default=())


GAME_CONFIGS: dict[str, GameConfig] = {
    "1": GameConfig(
        name="Dark Souls III (黑暗之魂3)",
        appdata_dir="DarkSoulsIII",
        file_ext="*.sl2",
        aes_key_hex="FD464D695E69A39A10E319A7ACE8B7FA",  # Atvaark 逆向发现
        struct_type="md5_iv_ct",
        steam_id_offset=0x08,
        user_data_id=10,
        bind_mode="internal",
        notes="已验证：AES [md5|iv|ct]，解密后偏移 0x08",
    ),
    "2": GameConfig(
        name="Dark Souls II / SOTFS (黑暗之魂2)",
        appdata_dir="DarkSoulsII",
        file_ext="*.sl2",
        # DS2S(SOTFS) 密钥；原版 DS2 用 B7FD463E4A9C1102DF1739E5F3B2A50F（未验证）
        aes_key_hex="599F9B699640A55236EE2D70835EC744",
        struct_type="md5_iv_ct",
        steam_id_offset=0x08,
        user_data_id=10,
        bind_mode="folder",  # .sl2 不内部绑定 SteamID，迁移靠文件夹名，纯复制
        notes="密钥已解(DS2S)。但 .sl2 不内部绑定 SteamID，迁移靠文件夹名",
    ),
    "3": GameConfig(
        name="Dark Souls Remastered (黑暗之魂重制版)",
        appdata_dir="DarkSoulsRemastered",
        file_ext="*.sl2",
        aes_key_hex="0123456789ABCDEFFEDCBA9876543210",  # DSR 密钥(soulsmods)
        struct_type="md5_iv_ct",
        steam_id_offset=0x08,
        user_data_id=10,
        bind_mode="folder",  # 实测 0x08 是版本字段；靠 STEAMID3 文件夹识别，纯复制
        notes="实测(2026-08-06)：不内部绑定 SteamID（0x08 是版本字段），靠 STEAMID3 文件夹迁移，同 DS2。"
              "存档在 Documents\\NBGI\\DARK SOULS REMASTERED(非%APPDATA%)，已支持自动扫描",
        # 实际存档在 Documents\NBGI\DARK SOULS REMASTERED（含 OneDrive 重定向变体）
        alt_save_roots=("NBGI/DARK SOULS REMASTERED",),
    ),
    "4": GameConfig(
        name="Elden Ring (艾尔登法环)",
        appdata_dir="EldenRing",
        file_ext="*.sl2",
        aes_key_hex="",
        struct_type="plain",   # USER_DATA_010 明文 + checksum
        steam_id_offset=0x14,
        user_data_id=10,
        bind_mode="internal",
        notes="已验证：明文，SteamID @ 0x14（黑盒 .co2 patch 闭环全过）",
    ),
    "5": GameConfig(
        name="Sekiro: Shadows Die Twice (只狼)",
        appdata_dir="Sekiro",
        file_ext="*.sl2",
        aes_key_hex="",
        struct_type="plain",
        steam_id_offset=0x34,
        user_data_id=10,
        bind_mode="internal",
        notes="已验证：明文，SteamID @ 0x34（真实存档命中）",
    ),
    "6": GameConfig(
        name="Elden Ring Nightreign (黑夜君临)",
        appdata_dir="Nightreign",
        file_ext="*.sl2",
        aes_key_hex="18F6326605BD178A5524523AC0A0C609",  # NR 密钥(Keys.cs)
        struct_type="iv_ct",
        steam_id_offset=0x08,
        user_data_id=10,
        bind_mode="internal",
        notes="已验证：AES [iv|ct]，NR 密钥，SteamID @ 0x08（真实存档命中）",
    ),
}

# struct_type → USER_DATA 条目头部长度（ct 之前的字节数；plain 为 0）
STRUCT_HEADER_LEN: dict[str, int] = {
    "plain": 0,
    "iv_ct": 16,     # iv(16) | ct
    "md5_iv_ct": 32,  # md5(16) | iv(16) | ct
}
