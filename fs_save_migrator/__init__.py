"""FS Save Migrator — FromSoftware 存档通用迁移工具
====================================================

在正版存档 ↔ 学习版存档、以及不同 Steam 账号之间双向迁移 .sl2 存档。
原理：解析 BND4 容器 → 定位 USER_DATA_010 → 读取/修改其中绑定的 SteamID
→ 写回新文件。**只改 SteamID，不动游戏数据**。

模块布局：
  games   游戏配置表（GameConfig + GAME_CONFIGS，新增游戏 = 加一条目）
  crypto  AES-128-CBC 加解密（cryptography 优先，PowerShell 回退）
  bnd4    BND4 容器解析 + USER_DATA 条目解封装（struct_type 三分支）
  migrate SteamID 提取/修改、文件夹名进制探测、存档目录扫描
  cli     交互式菜单
"""
from .bnd4 import Bnd4Entry, decrypt_user_data_entry, find_user_data_010, parse_bnd4_entries
from .crypto import HAS_CRYPTOGRAPHY, aes_decrypt, aes_encrypt
from .games import GAME_CONFIGS, STRUCT_HEADER_LEN, GameConfig
from .migrate import (
    extract_steam_id,
    is_valid_save_folder_name,
    parse_folder_name_steamid,
    patch_steam_id,
    scan_save_folders,
)

__version__ = "2.0.0"
__all__ = [
    "GAME_CONFIGS",
    "GameConfig",
    "STRUCT_HEADER_LEN",
    "HAS_CRYPTOGRAPHY",
    "Bnd4Entry",
    "aes_decrypt",
    "aes_encrypt",
    "decrypt_user_data_entry",
    "extract_steam_id",
    "find_user_data_010",
    "is_valid_save_folder_name",
    "parse_bnd4_entries",
    "parse_folder_name_steamid",
    "patch_steam_id",
    "scan_save_folders",
    "__version__",
]
