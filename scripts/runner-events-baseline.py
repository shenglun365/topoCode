"""固化 runner 事件 schema 基线（R2 契约门禁）。

以 packages/core/topoone/plugins/runner/events.py 的 schema_snapshot() 为单源，
写入 packages/core/runner-events-baseline.json（与 rpc-method-baseline.json 同模式）。

用法（仓库根目录）：
  python3 scripts/runner-events-baseline.py

契约纪律（只增不改）：既有 kind/字段形状冻结；新增 kind/extra 字段为向后兼容。
重生成基线 = 有意的契约变更，须在 PR 描述标注 runner 事件破坏面
（turn_adapter 协议 / 事件 schema / 续跑格式），并同步评估 architect 泵消费面
（apps/architect agent/execution + exec_bridge）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE_PATH = ROOT / "packages" / "core" / "runner-events-baseline.json"

sys.path.insert(0, str(ROOT))

from topoone.plugins.runner.events import schema_snapshot  # noqa: E402


def main() -> int:
    payload = {
        "baselineVersion": 1,
        "description": "runner JobEvent 事件 schema 基线（R2 契约门禁；只增不改："
                       "既有字段形状冻结，新增 kind/extra 向后兼容）",
        "schema": schema_snapshot(),
    }
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"[events-baseline] wrote {BASELINE_PATH.relative_to(ROOT)} "
          f"({payload['schema']['kindCount']} kinds)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
