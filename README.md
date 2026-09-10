# FS Save Migrator — FromSoftware 存档通用迁移工具

将 **正版存档 ↔ 学习版存档**、**不同 Steam 账号之间** 的存档双向一键迁移。支持 **黑暗之魂全系列、艾尔登法环、只狼、黑夜君临** 共 6 款 FromSoftware 游戏。

原理：解析 BND4 容器 → 定位 `USER_DATA_010` → 读取/修改其中绑定的 SteamID → 写回新文件。**只改 SteamID，不动游戏数据**。

## 快速开始

```bash
# 完整版（推荐，自动 AES 加解密）
pip install cryptography
python fs_save_migrate.py

# 如果不想装依赖，自动回退到 PowerShell（仅 Windows，较慢）
python fs_save_migrate.py
```
> **提示**：工具会自动备份目标文件夹的原存档为 `.bak` 文件，迁移后可手动删除或恢复。

运行后：
1. 选择游戏
2. 选择源存档和目标存档（支持扫描列表或手动输入路径）
3. 选择转换方向（源→目标 或 目标→源）
4. 确认，完成

---

## 支持的游戏

以下为 **真实存档闭环验证**（extract → patch → re-extract，2026-08 实测）后的状态：

| # | 游戏 | 存档路径 | 绑定方式 | 状态 |
|---|------|----------|----------|------|
| 1 | **Dark Souls III** (黑暗之魂3) | `%APPDATA%\DarkSoulsIII\` | 存档内绑定（patch） | ✅ 已验证 |
| 2 | **Dark Souls II / SOTFS** (黑暗之魂2) | `%APPDATA%\DarkSoulsII\` | 文件夹名识别（纯复制） | ✅ 已验证 |
| 3 | **Dark Souls Remastered** (黑暗之魂重制版) | `Documents\NBGI\DARK SOULS REMASTERED\`（**非 %APPDATA%**） | 文件夹名识别（纯复制） | ✅ 已验证 |
| 4 | **Elden Ring** (艾尔登法环) | `%APPDATA%\EldenRing\` | 存档内绑定（patch） | ✅ 已验证（含黑盒 `.co2` 备份） |
| 5 | **Sekiro: Shadows Die Twice** (只狼) | `%APPDATA%\Sekiro\` | 存档内绑定（patch） | ✅ 已验证 |
| 6 | **Elden Ring Nightreign** (黑夜君临) | `%APPDATA%\Nightreign\` | 存档内绑定（patch） | ✅ 已验证 |

两种绑定方式的含义：

- **存档内绑定（patch）**：SteamID 存在存档文件内部，工具解密（若加密）→ 改 8 字节 SteamID → 重新封装写入目标文件夹。
- **文件夹名识别（纯复制）**：DS2 / DSR 的存档**不在内部绑定 SteamID**，游戏靠存档文件夹名（SteamID 字符串）识别账号。迁移只需把 `.sl2` 复制到目标账号的文件夹，工具做字节级一致的纯复制。

### 为什么不支持以下游戏？

| 游戏 | 原因 |
|------|------|
| **Bloodborne** (血源诅咒) | PSN 账号绑定，非 SteamID 机制，存档加密方式不同 |
| **Armored Core VI** (装甲核心6) | 使用不同的存档加密方案，非 BND4 格式 |
| **Dark Souls: Prepare to Die** (原版黑魂1) | 非 Steam 版（GFWL 时代），存档格式不同 |
| **Demon's Souls** (恶魔之魂) | PS3/PS5 独占，非 Steam 平台 |

---

## 双向转换说明

### 场景 1：正版 → 学习版

```
你有一个正版打了 100 小时的存档，想转到学习版玩 Mod。
```

1. 运行学习版，**随便建一个新存档**然后退出（生成学习版存档文件夹）
2. 运行本工具，选择游戏 → 选正版存档为"源" → 选学习版存档为"目标"
3. 方向选 **"源 → 目标"**
4. 工具将正版存档的 SteamID 改成学习版的，并写入学习版文件夹
5. 启动学习版即可读取

### 场景 2：学习版 → 正版

```
你在学习版上打了 Mod 通关了，想把存档转回正版继续联机。
```

1. 运行本工具，选择游戏 → 选学习版存档为"源" → 选正版存档为"目标"
2. 方向选 **"源 → 目标"**
3. 工具将学习版存档的 SteamID 改成正版的，并写入正版文件夹
4. 启动正版即可读取

### 场景 3：账号 A → 账号 B（同一游戏，不同 Steam 账号）

```
你换了个 Steam 小号，想把大号的存档转过去。
```

流程同上，选择两个不同 Steam 账号对应的存档文件夹即可。
> **注意**：请确保源与目标为不同文件夹；方向 2（目标→源）要求目标文件夹必须已存在有效存档文件。

---

## 原理详解（按实测事实）

### 为什么这些游戏可以共用同一个工具？

FromSoftware 自 **Dark Souls II** 起统一用 **BND4 容器** 存储存档，存档与 Steam 账号绑定。但**各游戏的加密方案、密钥、SteamID 存放位置并不相同**——这是对真实存档逐款逆向实测后的结论，本工具的全部差异都收敛在一张配置表 `GAME_CONFIGS` 里。

#### 1. 容器格式：BND4（全系列相同）

```
┌─────────────────────────────────────────┐
│  BND4 Header (0x00-0x3F)                  │
│  magic="BND4" + 文件大小 + 预留字段       │
├─────────────────────────────────────────┤
│  Entry Table (从 0x40 开始, 每条目 32 字节) │
│  每个条目: unk(16) + 数据偏移(4) + 大小(4) + unk(8) │
├─────────────────────────────────────────┤
│  USER_DATA_000 ~ 009  → 角色存档槽位     │
│  USER_DATA_010       → 全局信息（含 SteamID）│
│  USER_DATA_011       → DCX 压缩数据      │
└─────────────────────────────────────────┘
```

工具按 **index 10**（第 11 个 entry）定位 `USER_DATA_010`，避免按名字解析在个别游戏（如 Nightreign 的 `TA010`）上误匹配。

#### 2. 各游戏实测参数表

`USER_DATA_010` 条目数据的封装结构分三种：

- `md5_iv_ct`：`[md5(16) | iv(16) | 密文]`，AES-128-CBC 加密
- `iv_ct`：`[iv(16) | 密文]`，AES-128-CBC 加密（无 md5 前缀）
- `plain`：明文存储，不加密（头部带 checksum）

| 游戏 | 封装结构 | AES-128 密钥 | SteamID 偏移 | 文件夹名进制 |
|------|----------|--------------|--------------|--------------|
| Dark Souls III | `md5_iv_ct` | `FD464D695E69A39A10E319A7ACE8B7FA` | 0x08（解密后） | 十六进制 SteamID64 |
| Dark Souls II / SOTFS | `md5_iv_ct` | `599F9B699640A55236EE2D70835EC744`（DS2S） | 不适用（不内部绑定） | 十六进制 SteamID64 |
| Dark Souls Remastered | `md5_iv_ct` | `0123456789ABCDEFFEDCBA9876543210` | 不适用（不内部绑定，0x08 处实测为版本字段） | account_id 十进制（= SteamID64 − 0x0110000100000000） |
| Elden Ring | `plain` | —（明文） | 0x14（原始字节） | 十进制 SteamID64 |
| Sekiro | `plain` | —（明文） | 0x34（原始字节） | 十进制 SteamID64 |
| Nightreign | `iv_ct` | `18F6326605BD178A5524523AC0A0C609` | 0x08（解密后） | 十进制 SteamID64 |

SteamID 均为 64 位整数、小端序 8 字节。

> **关键认知（踩坑史）**：早期"5 款游戏同密钥同结构共用 0x08"的假设是**错的**——实测各游戏加密方案、密钥、偏移各不相同（DS3 加密、Sekiro/ER 明文、DS2/DSR/NR 各有独立密钥）。新增游戏时以 `GAME_CONFIGS` 为准，勿凭直觉套用。

#### 3. 文件夹名 = SteamID 字符串（进制因游戏而异）

`存档目录` 下的每个存档文件夹名是该存档所属 SteamID 的字符串表示。工具用 `parse_folder_name_steamid()` 自动探测进制：

- 含字母 a-f → 必为十六进制
- `7656119` 前缀 → 十进制 SteamID64
- `01100001` 前缀 → 十六进制 SteamID64
- 纯数字且非上述前缀（DSR）→ account_id 十进制，加 `0x0110000100000000` 还原 SteamID64

目录列表展示时，工具会交叉验证「文件夹名 SteamID」与「存档内 SteamID」，两者不一致提示存档可能损坏或来自不同账号。

#### 4. 迁移流程

```
源存档.sl2
    │
    ├─ 解析 BND4，按 index 10 定位 USER_DATA_010
    │
    ├─ folder 模式（DS2/DSR）：不解密不改字节，整文件纯复制到目标文件夹
    │
    └─ internal 模式（DS3/ER/Sekiro/NR）：
         ├─ md5_iv_ct / iv_ct：AES-128-CBC 解密
         ├─ 修改偏移处的 8 字节 SteamID（小端 uint64）
         ├─ AES 重新加密，保留原 MD5 / IV / trailer
         └─ 写回 BND4 容器（plain 结构直接改原始字节，保留原 checksum）
    │
    ▼
目标账号可用存档
```

- patch 时**保留原 MD5 / IV / checksum** 等校验字段，实测游戏可正常读取（闭环验证通过）
- 整个过程**不修改源文件**，输出写入目标文件夹
- 写入前自动把目标原文件备份为 `.bak`

---

## 文件说明

| 文件/目录 | 说明 |
|------|------|
| `fs_save_migrator/` | **Python 包（主体）** — games / crypto / bnd4 / migrate / cli 五个模块 |
| `fs_save_migrate.py` | 兼容入口（旧命令 `python fs_save_migrate.py` 不变） |
| `scan_offset.py` | 逆向辅助：对真实存档解密 `USER_DATA_010` 搜索 SteamID 字节序列，自动定位偏移 |
| `tests/` | pytest 套件：合成 BND4 全结构闭环 + 真实存档回归（存档缺失自动跳过） |
| `pyproject.toml` | 打包与工具链配置（`pip install -e ".[dev]"` 后可用 `fs-save-migrator` 命令） |
| `fs_save_migrator.spec` | PyInstaller 单文件 exe 打包配置（可选） |

### 依赖说明

- **推荐安装 `cryptography` 库**：`pip install cryptography`，速度快
- **不安装也能用**：自动回退到 Windows PowerShell + .NET 做 AES，但速度较慢；Linux/macOS 必须安装 `cryptography`
- Python 3.10+

---

## 安全说明

### 软 Ban 风险

> ⚠️ **修改存档并加载回在线模式可能导致软封禁（Softban）。**

- 本工具**仅修改 SteamID**，不修改游戏数据（魂量、等级、物品等）
- 理论上通过存档一致性检查，但 **无绝对保证**
- 学习版游玩时建议**完全断开网络连接**（Steam 离线模式不够）
- 正版联机前确保存档来源合法

### 回滚方法

工具会自动备份目标文件夹的原存档为 `.bak` 文件。如需恢复：
1. 删除新生成的存档文件
2. 将 `.bak` 文件重命名为原名

### 其他

- 本工具**不联网**，所有操作在本地完成
- 支持**手动指定路径**（自动扫描不到时，兼容黑盒语音等第三方备份的 `.co2` / `.bak` 文件）

---

## 参考资料

- [SoulsFormats](https://github.com/JKAnderson/SoulsFormats) — FromSoftware 存档格式逆向库
- [DarkSoulsIII.FileFormats](https://github.com/Atvaark/DarkSoulsIII.FileFormats) — Atvaark 对 BND4 格式的分析
- AES 密钥 `FD464D695E69A39A10E319A7ACE8B7FA`（DS3）由 [Atvaark](https://github.com/Atvaark) 逆向发现；DS2S / DSR / Nightreign 密钥来自社区公开逆向成果（soulsmods、Keys.cs 等），来源注释见 `fs_save_migrate.py` 的 `GAME_CONFIGS`
