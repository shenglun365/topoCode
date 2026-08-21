"""固化 RPC 方法集基线（M01 / G2 门禁）。

以进程内方式启动核心注册逻辑（BackendApp.register_all），dump 全量
`server.methods` 键集到 packages/core/rpc-method-baseline.json。

用法（仓库根目录）：
  python3 scripts/rpc-baseline.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rpc_common import BASELINE_PATH, collect_methods  # noqa: E402


def main() -> int:
    methods = collect_methods()
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(methods),
        "methods": methods,
    }
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"[rpc-baseline] wrote {BASELINE_PATH.relative_to(Path(__file__).resolve().parent.parent)} ({len(methods)} methods)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
