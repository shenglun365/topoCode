"""RPC 方法集采集 — rpc-baseline.py / check-rpc-parity.py 共享逻辑（M01 / G2 门禁）。"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE_PATH = ROOT / "packages" / "core" / "rpc-method-baseline.json"


def collect_methods() -> list[str]:
    """进程内采集「合并方法集」，返回排序后的方法名列表。

    M11：render.* 已移入 docs 子项目（独立进程 :3481），核心不再注册。为保持 G2
    对外方法契约对等，基线采集从「核心单进程」升级为「核心 + docs 服务」并集
    （report.* 保留核心，无需并入；docs 仅贡献 render.*）。
    """
    from topoone.engine.app import BackendApp  # noqa: E402  (topoone editable 安装)

    tmp_dir = tempfile.mkdtemp(prefix="topo-rpc-baseline-")
    app = BackendApp(data_dir=tmp_dir)
    try:
        app.register_all()
        methods = set(app.server.methods.keys())
    finally:
        app.multi_db.close_all()
        import shutil

        shutil.rmtree(tmp_dir, ignore_errors=True)

    # docs 服务：render.*（独立进程，进程内模拟其注册；render 注册不依赖 multi_db）
    try:
        from topoone.rpc.service_app import MethodServer
        from topoone_app_docs.main import register_methods as docs_register
        docs_server = MethodServer(pub_port=None)
        docs_register(docs_server, None)
        methods.update(docs_server.methods.keys())
    except Exception as e:  # docs 包不可用时退化为仅核心方法集
        print(f"[rpc-common] docs methods skipped: {e}", file=sys.stderr)

    return sorted(methods)


def load_baseline() -> list[str]:
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))["methods"]
