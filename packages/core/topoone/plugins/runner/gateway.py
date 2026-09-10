"""AgentGateway — 执行器注册表与配置中枢。

配置源（优先级）：
  1. architect `GET /api/architect/agent/executors/runtime`（存 arch_collab_config
     ["agent.executors"]，系统管理 UI 可编辑；token 取 ~/.topocode/token）
  2. 环境变量（旧 RUNNER_DEFAULT_EXECUTOR/OPENCODE_SERVE_URL/CODEX_CMD/CLAUDE_CMD 兼容）
  3. 内置默认（opencode 会话化 + cline 自主模式 + mock）

刷新语义：architect 保存配置后 POST /api/executors/refresh → 重建执行器并
register() 进现有 pool（同 id 覆盖）；默认执行器 id 变化时整体换池
（scheduler._pool 在叶任务间原子替换，运行中叶子不受影响）。
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

import httpx

from topocode_agent.orchestration.scheduler import TaskTreeScheduler
from topocode_agent.subagent import CliExecutor, ExecutorPool
from topocode_agent.subagent.protocol import MockCodingExecutor

from .executors.cline import ClineSdkExecutor
from .executors.remote import RemoteAgentExecutor
from .executors.codex_server import CodexServerExecutor
from .executors.opencode import OpenCodeSessionExecutor

logger = logging.getLogger(__name__)

ARCH_BASE_URL = os.environ.get("ARCH_BASE_URL", "http://127.0.0.1:3470")


def _token() -> str:
    for p in (os.environ.get("TOPOCODE_TOKEN_FILE"),
              os.path.join(os.path.expanduser("~"), ".topocode", "token")):
        if p and os.path.isfile(p):
            try:
                return open(p).read().strip()
            except Exception:  # noqa: BLE001
                pass
    return ""


def _git_diff_names(root: str, base_commit: str) -> list[str]:
    """base...HEAD 变更文件（remote 执行器结果拉回后用）。"""
    import subprocess
    try:
        p = subprocess.run(["git", "diff", "--name-only", f"{base_commit}...HEAD"],
                           cwd=root, capture_output=True, text=True, timeout=60)
        if p.returncode != 0:
            return []
        return [l.strip() for l in p.stdout.splitlines() if l.strip()]
    except Exception:  # noqa: BLE001
        return []


def _prompt_builder():
    from topocode_agent.core.context import default_coding_prompt_builder
    return default_coding_prompt_builder(os.environ.get("RUNNER_PROJECT_ROOT", ""))


# ── 配置默认值 ──

BUILTIN_DEFAULT = [
    {
        "id": "opencode", "type": "opencode", "enabled": True, "default": True,
        "config": {"auto_start": True, "base_port": 3478, "permission": "auto",
                   "timeout": 1800},
    },
    {
        "id": "cline", "type": "cline-sdk", "enabled": True, "default": False,
        "config": {"provider_id": "", "model_id": "", "api_key": "",
                   "max_iterations": 40},
    },
    {"id": "mock", "type": "mock", "enabled": True, "default": False, "config": {}},
]


def _env_entries() -> list[dict]:
    """旧环境变量 → 注册表条目（无则空）。"""
    entries: list[dict] = []
    if os.environ.get("OPENCODE_SERVE_URL"):
        entries.append({
            "id": "opencode", "type": "serve-generic", "enabled": True,
            "default": os.environ.get("RUNNER_DEFAULT_EXECUTOR", "opencode") == "opencode",
            "config": {"base_url": os.environ["OPENCODE_SERVE_URL"],
                       "api_key": os.environ.get("OPENCODE_API_KEY", "")},
        })
    if os.environ.get("CODEX_CMD"):
        entries.append({
            "id": "codex", "type": "cli", "enabled": True,
            "default": os.environ.get("RUNNER_DEFAULT_EXECUTOR") == "codex",
            "config": {"command": os.environ["CODEX_CMD"], "timeout": 600},
        })
    # claude-code 执行器暂不提供（产品决策 2026-09）
    return entries


async def fetch_runtime_config(retries: int = 0, delay_s: float = 3.0) -> Optional[list[dict]]:
    """从 architect 拉取执行器注册表（不可达/未配置 → None）。

    retries>0 用于启动竞态（supervisor 同时拉起 runner 与 architect，
    architect 未就绪时重试，避免静默回退内置池）。
    """
    tk = _token()
    if not tk:
        return None
    for attempt in range(retries + 1):
        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                r = await client.get(
                    f"{ARCH_BASE_URL}/api/architect/agent/executors/runtime",
                    headers={"Authorization": f"Bearer {tk}"})
                if r.status_code == 200:
                    data = (r.json() or {}).get("data") or {}
                    entries = data.get("executors")
                    if isinstance(entries, list) and entries:
                        return entries
        except Exception as e:  # noqa: BLE001
            if attempt >= retries:
                logger.info("[gateway] architect 配置不可达（%s），用 env/内置默认", e)
        else:
            if attempt >= retries:
                return None
        await asyncio.sleep(delay_s)
    return None


def resolve_entries(arch_entries: Optional[list[dict]]) -> list[dict]:
    if arch_entries:
        return [e for e in arch_entries if e.get("enabled", True)]
    env = _env_entries()
    if env:
        return env
    return [dict(e) for e in BUILTIN_DEFAULT]


def _clamp_model(cfg: dict) -> dict:
    """模型白名单钳制(cfg.models 非空时生效)。

    运行时只在实例模型白名单内取模型: entry.config.model 不在白名单
    (或为空)→ 回退白名单首项。杜绝旁路调用 opencode/codex 服务里已配置
    但 architect 未纳入的模型(避免误消耗高付费 API)。
    """
    models = cfg.get("models") or []
    if not isinstance(models, list) or not models:
        return cfg
    allowed = set()
    for m in models:
        if isinstance(m, dict):
            for k in ("name", "model"):
                if m.get(k):
                    allowed.add(str(m[k]))
    cur = str(cfg.get("model") or "").strip()
    if cur in allowed:
        return cfg
    first = models[0] if isinstance(models[0], dict) else {}
    cfg["model"] = first.get("model") or first.get("name") or ""
    return cfg


def _build_one(entry: dict, pb) -> Optional[object]:
    eid = (entry.get("id") or "").strip()
    etype = entry.get("type") or ""
    cfg = entry.get("config") or {}
    if not eid:
        return None
    cfg = _clamp_model(dict(cfg))
    try:
        if etype == "opencode":
            return OpenCodeSessionExecutor(
                id=eid, base_url=cfg.get("base_url", ""), api_key=cfg.get("api_key", ""),
                timeout=float(cfg.get("timeout", 1800)),
                auto_start=bool(cfg.get("auto_start", True)),
                base_port=int(cfg.get("base_port", 3478)),
                permission=cfg.get("permission", "auto"),
                model=cfg.get("model", ""), opencode_bin=cfg.get("opencode_bin", ""),
                prompt_builder=pb)
        if etype == "cline-sdk":
            return ClineSdkExecutor(
                id=eid, node_bin=cfg.get("node_bin", "node"),
                sidecar_script=cfg.get("sidecar_script", ""),
                provider_id=cfg.get("provider_id", ""), model_id=cfg.get("model_id", ""),
                api_key=cfg.get("api_key", ""), base_url=cfg.get("base_url", ""),
                max_iterations=int(cfg.get("max_iterations", 40)),
                arch_url=cfg.get("arch_url", ARCH_BASE_URL), arch_token="",
                timeout=float(cfg.get("timeout", 3600)), prompt_builder=pb)
        if etype == "remote-agent":
            return RemoteAgentExecutor(
                id=eid, agent_url=cfg.get("agent_url", ""),
                api_key=cfg.get("api_key", ""),
                git_remote=cfg.get("git_remote", "auto"),
                arch_url=cfg.get("arch_url", ARCH_BASE_URL),
                timeout=float(cfg.get("timeout", 3600)),
                permission=cfg.get("permission", "auto"),
                model=cfg.get("model", ""), prompt_builder=pb)
        if etype == "codex-server":
            return CodexServerExecutor(
                id=eid, codex_bin=cfg.get("codex_bin", "codex"),
                codex_home=cfg.get("codex_home", ""),
                timeout=float(cfg.get("timeout", 3600)),
                approval_policy=cfg.get("approval_policy", "never"),
                sandbox_mode=cfg.get("sandbox_mode", "workspace-write"),
                model=cfg.get("model", ""), prompt_builder=pb)
        if etype == "cli":
            cmd = cfg.get("command", "")
            if not cmd:
                return None
            return CliExecutor(id=eid, command=cmd,
                               timeout=float(cfg.get("timeout", 600)))
        if etype == "serve-generic":
            from topocode_agent.subagent import ServeExecutor
            return ServeExecutor(id=eid, base_url=cfg.get("base_url", ""),
                                 api_key=cfg.get("api_key", ""),
                                 timeout=float(cfg.get("timeout", 300)), prompt_builder=pb)
        if etype == "mock":
            return MockCodingExecutor()
        logger.warning("[gateway] 未知执行器类型 %s (%s)", etype, eid)
        return None
    except Exception as e:  # noqa: BLE001
        logger.warning("[gateway] 构建执行器 %s 失败: %s", eid, e)
        return None


class AgentGateway:
    """runner 内的执行器注册表/会话注册中心。"""

    def __init__(self):
        self._session_executors: dict[str, object] = {}  # executorId → executor(有 inject/abort)

    async def build_pool(self, boot: bool = False) -> tuple[ExecutorPool, list[dict]]:
        entries = resolve_entries(await fetch_runtime_config(retries=4 if boot else 0))
        pb = _prompt_builder()
        executors, default = [], None
        for e in entries:
            ex = _build_one(e, pb)
            if ex is None:
                continue
            executors.append(ex)
            if e.get("default") and default is None:
                default = ex
            if hasattr(ex, "inject") and hasattr(ex, "abort"):
                self._session_executors[ex.id] = ex
        if default is None:
            default = MockCodingExecutor()  # 兜底：注册表全灭时树可跑通（结果标记 mock）
            executors.append(default)
        pool = ExecutorPool(
            default_executor=default, executors=executors,
            max_parallel=int(os.environ.get("RUNNER_MAX_PARALLEL", "2")))
        return pool, entries

    async def apply_to(self, scheduler: TaskTreeScheduler) -> list[dict]:
        """构建并原子换池（叶任务间生效）。"""
        pool, entries = await self.build_pool()
        scheduler._pool = pool  # noqa: SLF001 — 叶间原子替换，运行中叶子不受影响
        return entries

    def find_session_executor(self, executor_id: str):
        return self._session_executors.get(executor_id)

    async def inject(self, session_key: str, message: str) -> dict:
        ex = self.find_session_executor(session_key.split(":", 1)[0])
        if ex is None:
            return {"ok": False, "error": f"executor 不支持会话注入: {session_key}"}
        return await ex.inject(session_key, message)

    async def abort_session(self, session_key: str) -> dict:
        ex = self.find_session_executor(session_key.split(":", 1)[0])
        if ex is None:
            return {"ok": False, "error": f"executor 不支持会话中止: {session_key}"}
        return await ex.abort(session_key)
