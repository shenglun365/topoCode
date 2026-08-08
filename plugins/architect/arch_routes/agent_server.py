"""AgentInstancePool — (project, adapter, host) 维度的 agent 运行实例管理。

四层模型:
  AgentConfig(连接模板) → AgentInstance(项目级运行实体) → AgentSession → ExecutionTask。

实例 key = (project_id, adapter, host)。host 为一等字段, 支持未来不同 IP 的远程实例:
  - managed : 后端在工程实现目录(root_path) spawn agent server(默认 opencode serve,
    只绑 127.0.0.1, 启动命令/健康探测来自 AgentAdapter);
  - external: 直连用户自启/远程 serve(host/port/url), 不管理进程。

代码事实源: 外部 git 仓库。agent 在 root_worker 建 task 分支提交并 push;
ARCHITECT/KB 各自从仓库拉取(arch_git / git_service), 本模块不触碰实例文件系统(除 managed cwd)。

生命周期: 懒启动、引用计数、空闲超时回收、health 崩溃标记、后端退出全停。
并发: max_instances 有界并行(默认 2), 超出等待(等待空闲实例释放)。

适配器: 进程/健康/会话客户端统一走 `agent_adapters` 注册表(当前仅 opencode)。
"""
import asyncio
import logging
import os
import socket
import subprocess
import time
from typing import Optional

from .common import _ts, _id
from . import store
from . import arch_git
from .agent_adapters import (
    AgentSession,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_USERNAME,
    ProcessSession,
    get_agent,
)

logger = logging.getLogger(__name__)

_READY_TIMEOUT = 30.0      # spawn 后等待 health 最长时间(秒)
_HEALTH_INTERVAL = 0.3     # 轮询间隔
_IDLE_TIMEOUT = 300        # 空闲超时(秒) → 回收
_MAX_INSTANCES = 2         # 跨项目同时实例数上限
_PORT_SCAN_START = 4096
_PORT_SCAN_END = 4296


def _free_port(start: int = _PORT_SCAN_START, end: int = _PORT_SCAN_END) -> int:
    for port in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            if s.connect_ex((DEFAULT_HOST, port)) != 0:
                return port
    raise RuntimeError("无可用端口(4096-4296 全被占用)")


class AgentInstancePool:
    """进程/直连实例注册表。key = (project_id, adapter, host)。"""

    def __init__(self):
        self._lock = asyncio.Lock()
        self._procs: dict[str, subprocess.Popen] = {}      # instance_id -> Popen
        self._running: dict[str, asyncio.Task] = {}        # instance_id -> health task
        self._stop_requested = False
        self._startup_lock: dict[str, asyncio.Lock] = {}

    # ── key ──────────────────────────────────────────────────

    @staticmethod
    def _key(project_id: str, adapter: str, host: str) -> str:
        return f"{project_id}|{adapter}|{host}"

    # ── 对外接口 ─────────────────────────────────────────────

    async def ensure(self, project: dict, cfg: dict) -> dict:
        """确保 (project, adapter, host) 实例就绪。返回实例行(dict, camelCase)。

        实例不存在 → 创建并(managed) spawn / (external) 探测；已存在且 ready → 直接返回。
        """
        project_id = project.get("id") or ""
        adapter = (cfg.get("adapter") or "opencode").lower()
        host = (cfg.get("host") or DEFAULT_HOST).strip()
        key = self._key(project_id, adapter, host)
        if key not in self._startup_lock:
            self._startup_lock[key] = asyncio.Lock()
        async with self._startup_lock[key]:
            inst = store.AgentInstancesStore.get_by_key(project_id, adapter, host)
            if inst and inst.get("state") in ("ready", "busy", "idle"):
                self._bump_ref(inst, project, cfg)
                return inst

            # 受管有界并行: 跨项目同时实例数上限。
            if not inst or inst.get("mode") != "external":
                await self._wait_capacity()

            if inst is None:
                inst = self._create_instance(project, cfg, host)
            else:
                inst = store.AgentInstancesStore.update(inst["id"], {
                    "state": "starting", "updatedAt": _ts(),
                }) or inst

            ok_ = await self._start(inst, project, cfg, host)
            if not ok_:
                store.AgentInstancesStore.update(inst["id"], {
                    "state": "error", "error": "启动失败或服务未就绪", "updatedAt": _ts(),
                })
                return store.AgentInstancesStore.get(inst["id"]) or inst
            return store.AgentInstancesStore.get(inst["id"]) or inst

    async def release(self, instance_id: str):
        """会话结束 → 引用减一；归零后置空闲(idle_until=now+_IDLE_TIMEOUT)。"""
        inst = store.AgentInstancesStore.get(instance_id)
        if not inst:
            return
        ref = max(0, int(inst.get("refCount") or 0) - 1)
        state = "idle" if ref == 0 else "busy"
        idle_until = (_ts() + _IDLE_TIMEOUT * 1000) if ref == 0 else 0
        store.AgentInstancesStore.update(instance_id, {
            "refCount": ref, "state": state, "idleUntil": idle_until, "updatedAt": _ts(),
        })

    async def stop(self, instance_id: str):
        """停止实例(managed terminate / external 仅置 stopped)并落库。"""
        proc = self._procs.pop(instance_id, None)
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except (subprocess.TimeoutExpired, OSError):
                try:
                    proc.kill()
                except OSError:
                    pass
        task = self._running.pop(instance_id, None)
        if task:
            task.cancel()
        store.AgentInstancesStore.update(instance_id, {
            "state": "stopped", "pid": 0, "port": 0,
            "refCount": 0, "idleUntil": 0, "updatedAt": _ts(),
        })

    async def shutdown_all(self):
        self._stop_requested = True
        for inst in store.AgentInstancesStore.all():
            if inst.get("pid"):
                await self.stop(inst["id"])

    async def reap_idle(self):
        """回收空闲超时实例(供周期任务调用)。"""
        now = _ts()
        for inst in store.AgentInstancesStore.all():
            if inst.get("state") == "idle" and inst.get("idleUntil") and now >= int(inst.get("idleUntil") or 0):
                logger.info(f"[AgentInstancePool] reaping idle instance {inst['id']}")
                await self.stop(inst["id"])

    # ── 内部 ─────────────────────────────────────────────────

    def _create_instance(self, project: dict, cfg: dict, host: str) -> dict:
        now = _ts()
        inst_id = _id("aginst")
        inst = {
            "id": inst_id,
            "projectId": project.get("id") or "",
            "adapter": (cfg.get("adapter") or "opencode").lower(),
            "host": host,
            "mode": (cfg.get("instanceMode") or cfg.get("mode") or "managed"),
            "state": "starting",
            "pid": 0, "port": 0,
            "workDir": project.get("rootPath") or "",
            "repoUrl": project.get("remoteUrl") or cfg.get("repoUrl") or "",
            "baseBranch": project.get("defaultBranch") or cfg.get("baseBranch") or "main",
            "baseCommit": project.get("baselineCommit") or "",
            "taskBranch": "",
            "lastCommit": "", "refCount": 0, "idleUntil": 0, "error": "",
            "createdAt": now, "updatedAt": now,
        }
        # 双模式写库(managed|external)。
        inst["mode"] = "external" if (cfg.get("url") or "").strip() else inst["mode"]
        store.AgentInstancesStore.create(inst)
        return store.AgentInstancesStore.get(inst_id) or inst

    def _bump_ref(self, inst: dict, project: dict, cfg: dict):
        ref = int(inst.get("refCount") or 0) + 1
        store.AgentInstancesStore.update(inst["id"], {
            "refCount": ref, "state": "busy", "idleUntil": 0, "updatedAt": _ts(),
            "workDir": project.get("rootPath") or inst.get("workDir") or "",
        })

    async def _wait_capacity(self):
        while True:
            active = [i for i in store.AgentInstancesStore.all()
                      if i.get("mode") != "external" and i.get("pid")]
            if len(active) < _MAX_INSTANCES:
                return
            await asyncio.sleep(1.0)

    async def _start(self, inst: dict, project: dict, cfg: dict, host: str) -> bool:
        adapter = get_agent(inst.get("adapter") or "opencode")
        if adapter is None:
            store.AgentInstancesStore.update(inst["id"], {
                "state": "error", "error": f"未知 adapter: {inst.get('adapter')}", "updatedAt": _ts(),
            })
            return False
        username = (cfg.get("username") or DEFAULT_USERNAME).strip()

        # cli 型: 无常驻进程。仅校验可执行文件存在, 即视为就绪。
        if getattr(adapter, "mode", "server") == "cli":
            if not adapter.health(inst.get("host") or host, username):
                store.AgentInstancesStore.update(inst["id"], {
                    "state": "error", "error": f"{adapter.id} CLI 未安装或不可用", "updatedAt": _ts(),
                })
                return False
            store.AgentInstancesStore.update(inst["id"], {
                "pid": 0, "port": int(cfg.get("port") or adapter.default_port) or 0,
                "state": "ready", "lastCommit": arch_git.head_commit(inst.get("workDir") or ""),
                "updatedAt": _ts(),
            })
            return True

        if inst.get("mode") == "external":
            addr = adapter.addr(cfg)
            if not adapter.health(addr, username):
                logger.warning(f"[AgentInstancePool] external serve 未就绪: {addr}")
                return False
            store.AgentInstancesStore.update(inst["id"], {
                "port": int(cfg.get("port") or DEFAULT_PORT), "state": "ready",
                "lastCommit": arch_git.head_commit(inst.get("workDir") or ""),
                "updatedAt": _ts(),
            })
            return True

        # managed: spawn serve in 工程实现目录。
        root = inst.get("workDir") or ""
        if not root or not os.path.isdir(root):
            store.AgentInstancesStore.update(inst["id"], {"error": "工程目录不存在", "updatedAt": _ts()})
            return False
        if not arch_git.verify_baseline(root, inst.get("baseCommit"))["ok"]:
            logger.warning(f"[AgentInstancePool] 基线校验不通过, 仅启动服务(不阻塞): {root}")
        port = _free_port()
        addr = f"http://{DEFAULT_HOST}:{port}"
        argv = adapter.spawn({"port": port})
        env = {**os.environ}
        extra = adapter.required_env(addr)
        if extra:
            env.update(extra)
        try:
            proc = subprocess.Popen(
                argv, cwd=root, env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except (FileNotFoundError, OSError) as e:
            logger.warning(f"[AgentInstancePool] 无法启动 {adapter.id} serve: {e}")
            return False
        self._procs[inst["id"]] = proc
        store.AgentInstancesStore.update(inst["id"], {
            "pid": proc.pid, "port": port, "state": "starting", "updatedAt": _ts(),
        })
        # 轮询 health。
        deadline = time.time() + _READY_TIMEOUT
        while time.time() < deadline:
            if proc.poll() is not None:
                return False
            if adapter.health(addr, username):
                store.AgentInstancesStore.update(inst["id"], {
                    "state": "ready", "lastCommit": arch_git.head_commit(root),
                    "updatedAt": _ts(),
                })
                self._running[inst["id"]] = asyncio.create_task(self._watch_health(inst["id"]))
                return True
            await asyncio.sleep(_HEALTH_INTERVAL)
        return False

    async def _watch_health(self, instance_id: str):
        """周期探测 health; 连续失败则标记 error(实例保留, 供重试/日志)。"""
        while not self._stop_requested:
            await asyncio.sleep(5)
            inst = store.AgentInstancesStore.get(instance_id)
            if not inst or not inst.get("pid"):
                return
            port = int(inst.get("port") or 0)
            if port <= 0:
                return
            adapter = get_agent(inst.get("adapter") or "opencode")
            if adapter is None:
                return
            addr = f"http://{DEFAULT_HOST}:{port}"
            username = DEFAULT_USERNAME
            if not adapter.health(addr, username):
                store.AgentInstancesStore.update(instance_id, {
                    "state": "error", "error": "health 检查失败(服务可能已退出)", "updatedAt": _ts(),
                })
                return


# 全局单例(独立进程内共享)。
_pool: Optional[AgentInstancePool] = None


def get_pool() -> AgentInstancePool:
    global _pool
    if _pool is None:
        _pool = AgentInstancePool()
    return _pool


# ── 会话客户端工厂(适配器驱动) ────────────────────────────────
# 兼容入口名 `opencode_client_for`, 实为按 adapter 构造对应会话客户端。
# 由 AgentAdapter.addr / make_client 统一, 不再硬编码 opencode 协议。

def agent_client_for(instance: dict, cfg: dict, adapter_id: str = "") -> AgentSession:
    """按实例/配置构造会话客户端(port 优先取实例已分配端口(managed)或配置端口(external))。"""
    adapter = get_agent(adapter_id or instance.get("adapter") or cfg.get("adapter") or "opencode")
    if adapter is None:
        raise ValueError(f"未知 adapter: {adapter_id or instance.get('adapter')}")
    addr = adapter.addr(cfg, instance)
    username = (cfg.get("username") or DEFAULT_USERNAME).strip()
    password = os.environ.get("OPENCODE_SERVER_PASSWORD", "")
    client = adapter.make_client(addr, username=username, password=password)
    # cli 型: 注入工程目录(供子进程 cwd)。
    if isinstance(client, ProcessSession):
        client.cfg = {**(client.cfg or {}), "workdir": instance.get("workDir") or cfg.get("workdir") or ""}
    return client


def opencode_client_for(instance: dict, cfg: dict) -> AgentSession:
    """兼容别名(调用方仍传 adapter=opencode), 实际走 adapter 注册表。"""
    return agent_client_for(instance, cfg, "opencode")
