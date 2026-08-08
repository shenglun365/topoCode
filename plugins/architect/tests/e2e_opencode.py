"""End-to-end: real opencode serve via AgentInstancePool → WS task flow (streaming).

Runs the real `_ensure_opencode_session` + `_run_opencode_task` chain against a
live `opencode serve` spawned by AgentInstancePool on a temp git project, and
asserts streamed message/done events reach a fake websocket.

A fresh isolated architect.db is used (ARCH_DATA_DIR → tempdir) so the real
user data store is never touched.

Run:
  python3 plugins/architect/tests/e2e_opencode.py
"""

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

REPO = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "backend-core"))

PROJ_ROOT = os.environ.get("E2E_PROJ_ROOT", "/tmp/e2e-proj")


def _git(*args) -> str:
    return subprocess.check_output(["git", "-C", PROJ_ROOT, *args], text=True).strip()


class FakeWS:
    def __init__(self):
        self.sent: list[dict] = []

    async def send_json(self, obj: dict) -> None:
        self.sent.append(obj)


async def main() -> int:
    from plugins.architect.arch_routes import ctx
    from plugins.architect.arch_routes import store
    from plugins.architect.arch_routes import websocket as WS

    # 独立临时库(避免污染真实 user db)。
    data_dir = tempfile.mkdtemp(prefix="e2e-arch-")
    os.environ["ARCH_DATA_DIR"] = data_dir
    ctx.setup(data_dir=data_dir)

    store.ProjectsStore.upsert("e2eproj", {
        "id": "e2eproj", "name": "e2e project", "rootPath": PROJ_ROOT,
        "defaultBranch": "main", "baselineCommit": _git("rev-parse", "HEAD"), "active": 1,
    })
    store.AgentConfigsStore.create({
        "id": "e2ecfg", "adapter": "opencode", "name": "opencode",
        "host": "127.0.0.1", "port": 0, "instanceMode": "managed",
    })

    # 跳过 git 同步(arch_git 拉取依赖远程; 此处只验 agent 执行链路)。
    WS._project_for_root = lambda root: None

    ws = FakeWS()
    # 与真实 WS 流程一致: session 先落库, 再走 _ensure_opencode_session。
    store.AgentSessionsStore.create({
        "id": "e2esess", "taskId": "e2e-exec", "adapter": "opencode",
        "status": "idle", "artifacts": [], "testResult": None,
        "stats": {}, "createdAt": 0, "updatedAt": 0,
    })
    exec_data = {"id": "e2e-exec", "adapter": "opencode", "runCount": 1, "taskBranch": "arch/e2e-task"}
    inst = await WS._ensure_opencode_session(PROJ_ROOT, None, exec_data, "e2esess")
    if not inst or inst.get("state") != "ready":
        print(f"E2E SKIP: opencode serve 未就绪 ({inst and inst.get('state')})")
        shutil.rmtree(data_dir, ignore_errors=True)
        return 2

    sess_row = store.AgentSessionsStore.get("e2esess") or {}
    oc_id = sess_row.get("opencodeSessionId") or ""
    if not oc_id:
        print("E2E FAIL: 未取得 opencode 会话 id")
        shutil.rmtree(data_dir, ignore_errors=True)
        return 1

    session = {
        "id": "e2esess", "taskId": "e2e-exec", "adapter": "opencode",
        "opencodeSessionId": oc_id, "instanceId": inst["id"],
        "model": os.environ.get("E2E_MODEL", ""),
        "stats": {}, "artifacts": [], "testResult": None,
    }
    await WS._run_opencode_task(
        ws, session, inst, {"title": "e2e smoke task", "context": ["需求: 初始化脚手架"]},
    )

    kinds = [e.get("type") for e in ws.sent]
    print("E2E event types:", kinds)
    n_msg = sum(1 for e in ws.sent if e.get("type") == "message")
    n_done = sum(1 for e in ws.sent if e.get("type") == "done")
    if "message" not in kinds or n_done != 1:
        print("E2E FAIL: 未收到流式 message / 唯一 done")
        shutil.rmtree(data_dir, ignore_errors=True)
        return 1
    print(f"E2E OK: {n_msg} message, 1 done")
    shutil.rmtree(data_dir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    try:
        code = asyncio.run(main())
    except Exception as e:  # pragma: no cover
        import traceback

        traceback.print_exc()
        code = 1
    raise SystemExit(code)
