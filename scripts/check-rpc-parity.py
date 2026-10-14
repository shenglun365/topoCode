"""G2 门禁 — RPC 方法集对等检查（M01）。

当前代码注册的全量方法集必须与 packages/core/rpc-method-baseline.json
完全一致（拆分移动代码不得改变对外方法契约）。

用法（仓库根目录）：
  python3 scripts/check-rpc-parity.py
退出码：0 = 对等；1 = 有差异（打印 added/removed）或基线缺失。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rpc_common import BASELINE_PATH, collect_methods, load_baseline  # noqa: E402


def main() -> int:
    if not BASELINE_PATH.is_file():
        print(f"[rpc-parity] baseline missing: {BASELINE_PATH}")
        print("[rpc-parity] run `python3 scripts/rpc-baseline.py` first")
        return 1
    expected = set(load_baseline())
    actual = set(collect_methods())

    added = sorted(actual - expected)
    removed = sorted(expected - actual)
    if not added and not removed:
        print(f"[rpc-parity] OK — {len(actual)} methods match baseline")
        return 0
    print(f"[rpc-parity] MISMATCH vs baseline ({len(expected)} methods)")
    if added:
        print(f"  added ({len(added)}):")
        for m in added:
            print(f"    + {m}")
    if removed:
        print(f"  removed ({len(removed)}):")
        for m in removed:
            print(f"    - {m}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
