#!/usr/bin/env python3
"""兼容入口：`python fs_save_migrate.py` 旧命令不变。

实际逻辑已拆分至 fs_save_migrator 包（games / crypto / bnd4 / migrate / cli）。
"""
from fs_save_migrator.cli import main

if __name__ == "__main__":
    main()
