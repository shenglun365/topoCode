"""固化 runner REST 面基线（R1 契约门禁）。

以 packages/core/topoone/plugins/runner/server.py 的 FastAPI app（含
implement.register 全量 /api/implement* 路由）的 OpenAPI paths 为单源，
写入 packages/core/runner-openapi-baseline.json。

用法（仓库根目录）：
  python3 scripts/runner-api-baseline.py

契约纪律：路径/方法集冻结——新增端点 = 追加（向后兼容）；改名/删除 = 破坏性
变更，须重生成基线、在 PR 描述标注 runner 破坏面，并同步 RunnerClient
（apps/architect agent/execution/runner_client.py）与前端消费面。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE_PATH = ROOT / "packages" / "core" / "runner-openapi-baseline.json"

sys.path.insert(0, str(ROOT))

from topoone.plugins.runner import implement, server  # noqa: E402


def collect_paths() -> dict:
    """采集 app OpenAPI paths → {path: sorted(methods)}（重复注册幂等）。"""
    implement.register(server.app)
    spec = server.app.openapi()
    return {path: sorted(methods.keys()) for path, methods in spec.get("paths", {}).items()}


def main() -> int:
    paths = collect_paths()
    payload = {
        "apiVersion": 1,
        "description": "runner REST 面基线（R1 契约门禁；路径/方法集冻结，新增端点=追加，"
                       "改名/删除=破坏性变更）",
        "pathCount": len(paths),
        "paths": paths,
    }
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"[runner-api-baseline] wrote {BASELINE_PATH.relative_to(ROOT)} "
          f"({len(paths)} paths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
