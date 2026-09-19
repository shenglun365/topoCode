#!/usr/bin/env python
"""基线/白名单再生器(门禁数据单源再生, 需 --confirm 显式确认)。

再生纪律(A2 审计修复):
    1. 默认 dry-run: 打印与现行 goldens 的 diff(新增/移除/行数变化),
       不写任何文件;
    2. --confirm 才落盘——再生即豁免, 落盘前必须人工过目 diff:
       - grep_whitelist 收缩(如链3迁移) = 正常棘轮收紧, 直接确认;
       - grep_whitelist 增长 = 违规新增(挡位字面量/llm_sync 新调用方),
         先修代码再再生, 不要带病确认;
       - line_baseline 新增 = 新文件(核对 ≤400 软上限或登记豁免);
         增长 = 存量回弹(应拆分而非登记)。
Run: python apps/architect/tests/goldens/regen_baselines.py [--confirm]
"""
import argparse
import json
import os
import re
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
PKG = os.path.join(REPO, "apps", "architect", "topoone_app_architect")
GOLDENS = os.path.dirname(os.path.abspath(__file__))


def _whitelisted_new_files():
    """test_file_size_gate.NEW_FILE_WHITELIST 键集(显式豁免的新文件不进基线,
    由新文件软上限门禁持续约束)。"""
    import re as _re
    t = open(os.path.join(GOLDENS, "..", "test_file_size_gate.py"),
             encoding="utf-8").read()
    m = _re.search(r"NEW_FILE_WHITELIST: dict = \{(.*?)\n\}", t, _re.DOTALL)
    if not m:
        return set()
    return set(_re.findall(r'"([^"]+)":', m.group(1)))


def _collect():
    _wl = _whitelisted_new_files()
    line_baseline = {}
    llm_sync_callers = []
    tier_files = []
    for sub in ("agent", "arch_routes"):
        root = os.path.join(PKG, sub)
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for fn in sorted(filenames):
                if not fn.endswith(".py"):
                    continue
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, PKG).replace(os.sep, "/")
                src = open(full, encoding="utf-8").read()
                if rel not in _wl:   # 显式豁免的新文件不进基线(软上限门禁约束)
                    line_baseline[rel] = len(src.splitlines())
                if "def llm_sync" in src:
                    pass
                elif re.search(r"\bllm_sync\s*\(", src):
                    llm_sync_callers.append(rel)
                if re.search(r"\bT[0-4]\b", src):
                    tier_files.append(rel)
    return {
        "line_baseline.json": json.dumps(line_baseline, ensure_ascii=False,
                                         indent=1, sort_keys=True) + "\n",
        "grep_whitelist.json": json.dumps(
            {"llm_sync_callers": sorted(llm_sync_callers),
             "tier_literal_files": sorted(tier_files)},
            ensure_ascii=False, indent=1) + "\n",
    }


def _diff(name, new_text):
    path = os.path.join(GOLDENS, name)
    if not os.path.exists(path):
        return [f"+ (新文件) {name}"]
    old = json.loads(open(path, encoding="utf-8").read())
    new = json.loads(new_text)
    out = []
    for k in sorted(set(old) | set(new)):
        ov, nv = old.get(k), new.get(k)
        if isinstance(ov, dict) and isinstance(nv, dict):
            continue
        if ov == nv:
            continue
        if ov is None:
            out.append(f"+ {k} = {nv}")
        elif nv is None:
            out.append(f"- {k} (移除)")
        else:
            out.append(f"~ {k}: {ov} -> {nv}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirm", action="store_true",
                    help="落盘(默认 dry-run 只打印 diff)")
    args = ap.parse_args()
    data = _collect()
    has_diff = False
    for name, text in data.items():
        d = _diff(name, text)
        if d:
            has_diff = True
            print(f"══ {name} ══")
            for line in d:
                print("  " + line)
    # 行数基线按文件级 diff 展示
    old = json.loads(open(os.path.join(GOLDENS, "line_baseline.json"),
                          encoding="utf-8").read())
    new = json.loads(data["line_baseline.json"])
    changed = [k for k in set(old) | set(new) if old.get(k) != new.get(k)]
    if changed:
        has_diff = True
        print(f"══ line_baseline.json: {len(changed)} 个文件行数变化 ══")
        for k in sorted(changed)[:40]:
            print(f"  ~ {k}: {old.get(k)} -> {new.get(k)}"
                  + ("  (新增)" if old.get(k) is None else ""))
        if len(changed) > 40:
            print(f"  … 共 {len(changed)} 项")
    if not has_diff:
        print("基线与白名单无变化。")
        return
    if args.confirm:
        for name, text in data.items():
            with open(os.path.join(GOLDENS, name), "w", encoding="utf-8") as f:
                f.write(text)
            print(f"已写入 {name}")
    else:
        print("\n(dry-run) 确认无误后加 --confirm 落盘。")


if __name__ == "__main__":
    sys.exit(main())
