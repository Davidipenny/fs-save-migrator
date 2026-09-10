# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置：产出单文件 exe（仅 Windows）
#
# 用法（在 fs-save-migrator/ 目录下）：
#   pip install -e ".[dev]"        # 含 pyinstaller
#   pyinstaller fs_save_migrator.spec
#
# 产物：dist/fs-save-migrator.exe — 双击或命令行运行，交互式菜单。
# 注意：工具不联网，杀软若误报属常见现象（未签名 PyInstaller 产物）。

a = Analysis(
    ["fs_save_migrate.py"],   # 兼容 shim：仅调用 fs_save_migrator.cli:main
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=["fs_save_migrator"],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="fs-save-migrator",
    console=True,
    upx=False,
)
