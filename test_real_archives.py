#!/usr/bin/env python3
"""真实存档回归验证
==================

用仓库根 `可用于检验的存档/` 下的真实游戏存档做回归：

  1. folder 模式（DS2/DSR）：extract 返回 None（不内部绑定 SteamID）
  2. folder 模式（DS2/DSR）：patch = 字节级一致的纯复制
  3. internal 模式（DS3）：patch 闭环（sid+1 写入后回读一致，源文件不变）

存档目录缺失（如 CI 或他人机器）时打印 SKIP 并以退出码 0 正常结束。
"""
import hashlib
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fs_save_migrate import GAME_CONFIGS, extract_steam_id, patch_steam_id

# 测试存档根目录：仓库根/可用于检验的存档（.gitignore 排除，仅本地存在）
ROOT = Path(__file__).resolve().parent.parent / "可用于检验的存档"

CASES = [
    ("2", "Darksouls2/0110000167dacdf4/DS2SOFS0000.sl2"),
    ("3", "DARK SOULS REMASTERED/1742392820/DRAKS0005.sl2"),
    ("1", "Darksouls3/0110000167dacdf4/DS30000.sl2"),
]

PASS = 0
FAIL = 0


def test(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print("  [OK] %s" % name)
    else:
        FAIL += 1
        print("  [FAIL] %s" % name + ("  -- %s" % detail if detail else ""))


def main():
    global PASS, FAIL
    print("=" * 60)
    print("  FS Save Migrator -- 真实存档回归验证")
    print("=" * 60)
    print("  存档目录: %s" % ROOT)

    if not ROOT.exists():
        print("\n  [SKIP] 存档目录不存在（仅本地保留，不入库），跳过全部用例")
        return 0

    missing = [rel for _, rel in CASES if not (ROOT / rel).exists()]
    if missing:
        print("\n  [SKIP] 缺少存档文件，跳过全部用例:")
        for rel in missing:
            print("    - %s" % rel)
        return 0

    # 用例 1: extract 行为符合 bind_mode 预期
    print("\n[1/3] extract 与 bind_mode 一致")
    for key, rel in CASES:
        cfg = GAME_CONFIGS[key]
        p = ROOT / rel
        sid = extract_steam_id(p, cfg)
        if cfg["bind_mode"] == "folder":
            test("[%s] %s: folder 模式 extract=None" % (key, cfg["name"]), sid is None,
                 "得到 %s" % sid)
        else:
            test("[%s] %s: internal 模式 extract 命中" % (key, cfg["name"]),
                 sid is not None and sid > 0, "得到 %s" % sid)

    # 用例 2: folder 模式 patch = 字节级一致纯复制
    print("\n[2/3] folder 模式 patch = 纯复制")
    for key, rel in CASES[:2]:
        cfg = GAME_CONFIGS[key]
        p = ROOT / rel
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / p.name
            ok = patch_steam_id(p, 123456789, out, cfg)
            same = (ok and out.exists()
                    and hashlib.md5(p.read_bytes()).hexdigest()
                    == hashlib.md5(out.read_bytes()).hexdigest())
            test("[%s] %s: 复制字节一致" % (key, cfg["name"]), same)

    # 用例 3: internal 模式 patch 闭环（DS3）
    print("\n[3/3] internal 模式 patch 闭环（DS3）")
    key, rel = CASES[2]
    cfg = GAME_CONFIGS[key]
    p = ROOT / rel
    sid = extract_steam_id(p, cfg)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out.sl2"
        ok = patch_steam_id(p, sid + 1, out, cfg)
        sid2 = extract_steam_id(out, cfg) if ok else None
        test("[1] DS3 patch 后 SteamID = 原值+1", sid2 == sid + 1,
             "期望 %s, 得到 %s" % (sid + 1, sid2))
        test("[1] 源文件未被修改", extract_steam_id(p, cfg) == sid)

    print("\n" + "=" * 60)
    print("  结果: %d 通过, %d 失败" % (PASS, FAIL))
    if FAIL == 0:
        print("  ALL PASSED!")
    else:
        print("  %d FAILED" % FAIL)
    print("=" * 60)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
