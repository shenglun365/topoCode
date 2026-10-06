"""三方 Coding Agent 执行器注册表 — architect 侧配置面。

存储：arch_collab_config["agent.executors"]（JSON 列表），
条目 {id, type, enabled, default, config{...}}，type ∈
  opencode      会话化 opencode serve（自动拉起/权限自动应答/会话 diff）
  cline-sdk     Cline sidecar（architect 自主模式，@cline/sdk 内嵌）
  cli           一次性 CLI 命令模板（codex exec / claude -p 兜底）
  serve-generic 旧一次性 serve 端点（/run 协议）
  mock          测试用

执行器配置为 architect 单源；作业按 executorId 显式路由到 runner
(POST /api/implement 携 executorType/executorConfig)，runner 无执行器池。
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import shutil
import logging
import os
import urllib.request
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Request

from ..common import _ts, ok, err
from .. import store
from .opencode_detect import (_detect_opencode_models, _probe_opencode_model,
                              _start_opencode_serve)

logger = logging.getLogger(__name__)

# 能力探测进行中守卫(环节十二b; 内存态——重启丢进行中任务, 结果已落注册表)
_CAP_PROBE_RUNNING: set = set()


def _runner_transport(path: str, payload=None, timeout: float = 12.0):
    """runner 访问端(probes.py transport 形; 惰性导入防环)。"""
    from ..agent.execution.exec_bridge import _runner
    return _runner(path, payload, timeout)
router = APIRouter()

CONFIG_KEY = "agent.executors"
RUNNER_BASE_URL = os.environ.get("RUNNER_BASE_URL", "http://127.0.0.1:3458")

DEFAULT_EXECUTORS = [
    {
        # cline 为默认核心执行器（ClineCore 会话宿主, 自主持有）
        "id": "cline", "type": "cline-sdk", "enabled": True, "default": True,
        "config": {"node_bin": "node", "sidecar_script": "",
                   "provider_id": "", "model_id": "", "api_key": "",
                   "max_iterations": 2000,  # 上限放大由循环护栏兜底(环节十一: 重复指纹/无进展/停滞看门狗), 正常消耗远低于此
                   "capability": "",        # 能力档位 T0-T4(空=未标定, 解析链落 T1; 十二b 探测写入 tierProbed)
                   "system_prompt": "", "tool_policies": {}, "models": [],
                   "mcp_servers": [],
                   "teams": {"enabled": False, "teamName": "", "agents": []}},
    },
    {
        "id": "opencode", "type": "opencode", "enabled": True, "default": False,
        "config": {"auto_start": True, "base_port": 3478, "permission": "auto",
                   "timeout": 1800, "model": "", "rulesMd": "", "mcp_servers": {}},
    },
]

_TYPES = {"opencode", "cline-sdk", "cli", "serve-generic", "codex-server", "remote-agent", "mock"}
_SECRET_KEYS = {"api_key"}
_HOSTS = {"local", "remote"}


def _norm_models(raw) -> list:
    """实例内模型列表归一化: [{id, name, model, url, apiKey?, maxTokens?}]。

    url 归一到 /v1 结尾(openai-compatible 惯例; cv-163: 缺 /v1 →
    LM Studio 200+JSON 错误体非 SSE → "stream ended without finish reason")。"""
    out = []
    for i, m in enumerate(raw if isinstance(raw, list) else []):
        if not isinstance(m, dict):
            continue
        name = str(m.get("name") or "").strip()
        model = str(m.get("model") or "").strip()
        if not name or not model:
            continue
        url = str(m.get("url") or "").strip().rstrip("/")
        if url and not url.endswith("/v1"):
            url = f"{url}/v1"
        out.append({
            "id": m.get("id") or f"m{i + 1}",
            "name": name, "model": model,
            "url": url,
            "apiKey": str(m.get("apiKey") or "").strip(),
            "maxTokens": int(m.get("maxTokens") or 0),
        })
    return out


def _builtin_cline_models() -> list[dict]:
    """内置 cline 模型面 = architect 实例模型实时投影(免白名单存储、免同步)。

    执行器只选定默认模型(model_id); 全量列表/端点/密钥随实例模型存取——
    白名单勾选与 provider/base_url/api_key 重复配置面退役(2026-09-19 裁决)。"""
    try:
        from .mcp_collab import get_llm_models
        out = []
        for m in (get_llm_models() or []):
            name, model = str(m.get("name") or ""), str(m.get("model") or "")
            if not name or not model:
                continue
            out.append({"id": str(m.get("id") or name), "name": name, "model": model,
                        "url": str(m.get("url") or ""),
                        "apiKey": str(m.get("apiKey") or ""),
                        "maxTokens": int(m.get("maxTokens") or 0)})
        return out
    except Exception:  # noqa: BLE001
        return []


def load_executors() -> list[dict]:
    raw = store.CollabConfigStore.get(CONFIG_KEY, "")
    if not raw:
        return json.loads(json.dumps(DEFAULT_EXECUTORS))
    try:
        entries = json.loads(raw)
        if isinstance(entries, list):
            _norm_iterations(entries)
            return _ensure_builtin(entries)
        return []
    except Exception:  # noqa: BLE001
        return []


def _ensure_builtin(entries: list[dict]) -> list[dict]:
    """cline 内置执行器自愈: 注册表缺失(旧数据/误删) → 注入默认条目置首。

    内置执行器免名称/类型配置、不可删除; 注册表已有用户默认执行器时
    自愈条目不抢 default(尊重用户选择)。"""
    if any((e or {}).get("id") == "cline" for e in entries):
        return entries
    builtin = json.loads(json.dumps(DEFAULT_EXECUTORS[0]))
    builtin["default"] = not any(e.get("default") for e in entries)
    return [builtin] + entries


# 环节十一: 轮次上限放大, 循环护栏(loopguard/无进展/停滞)兜底异常浪费。
# 存量注册表归一只替换已知旧默认(60/120), 不覆盖用户显式调优值。
_MAX_ITERATIONS_DEFAULT = 2000
_OLD_ITERATION_DEFAULTS = (60, 120)


def _norm_iterations(entries: list) -> None:
    for e in entries:
        cfg = (e or {}).get("config")
        if isinstance(cfg, dict) and cfg.get("max_iterations") in _OLD_ITERATION_DEFAULTS:
            cfg["max_iterations"] = _MAX_ITERATIONS_DEFAULT


# ── 执行器选定单源(v2): 别名归一 + 注册表默认 ────────────────────────
# 教训(cv-153): 任务链三处字面 "opencode" 兜底 + "cline"/"cline-sdk" 类型名
# 不一致 → 用户注册表 default=cline 被无视/runner 静默降级。全部收口到本节。

_TYPE_ALIASES = {"cline": "cline-sdk", "codex": "codex-server"}


def normalize_executor_type(etype: str) -> str:
    """执行器类型别名归一: cline→cline-sdk / codex→codex-server(单点)。"""
    return _TYPE_ALIASES.get((etype or "").strip(), (etype or "").strip())


def default_executor() -> Optional[dict]:
    """注册表默认执行器(default=true 且 enabled)——任务链缺省选定唯一来源。

    无显式指定时的兜底真相源; 找不到返回 None(调用方必须显式失败, 不得
    再回落特定执行器)。"""
    try:
        for e in load_executors():
            if e.get("default") and e.get("enabled", True):
                return e
        for e in load_executors():   # 无显式 default → 首个启用项(确定性)
            if e.get("enabled", True):
                return e
    except Exception:  # noqa: BLE001
        return None
    return None


def save_executors(entries: list[dict]) -> None:
    store.CollabConfigStore.set(CONFIG_KEY, json.dumps(entries, ensure_ascii=False))


def _normalize(entries: list[dict]) -> list[dict]:
    """旧数据兜底: PR2 之前的存量注册项缺 host 字段 → 默认 local。

    不兜底会导致: GET 返回 host=None(前端下拉显示空) 且 PUT 校验
    e.get("host", "local") 命中已存在的 None 值而误判非法。
    """
    for e in entries:
        if not e.get("host"):
            e["host"] = "local"
        if "enabled" not in e:
            e["enabled"] = True
    return entries


def _validate(entries: list[dict]) -> Optional[str]:
    ids = set()
    defaults = 0
    for e in entries:
        eid = (e.get("id") or "").strip()
        if not eid:
            return "执行器 id 不能为空"
        if eid in ids:
            return f"执行器 id 重复: {eid}"
        ids.add(eid)
        if e.get("type") not in _TYPES:
            return f"未知执行器类型: {e.get('type')}"
        if e.get("host", "local") not in _HOSTS:
            return f"非法 host: {e.get('host')}(local|remote)"
        cfg = e.get("config") or {}
        cfg["models"] = _norm_models(cfg.get("models"))
        names = [m["name"] for m in cfg["models"]]
        if len(names) != len(set(names)):
            return f"执行器 {eid} 模型名称重复"
        # 能力档位写侧校验(环节十二a): 空=未标定(解析链落默认 T1)。
        # 刻度 T0-T2; 旧刻度 T3/T4 写侧归一(2026-09-17 收敛)。
        cap = str(cfg.get("capability") or "").strip().upper()
        if cap and cap not in ("T0", "T1", "T2"):
            from ..agent.governance.gears import normalize_mode as _nm
            cap = _nm(cap)
        if cap and cap not in ("T0", "T1", "T2"):
            return f"执行器 {eid} 能力档位非法: {cap!r}(允许 T0-T2 或留空)"
        cfg["capability"] = cap
        # 模型配置写入校验(cline-sdk, cv-163/166/168 教训: 空 model/悬空默认/
        # 坏 url 均运行期才炸; opencode 等类型 models.url 为可选元数据不强制)。
        # 内置 cline 豁免: 模型面=实例模型实时投影(GET/下发时注入, 不落盘),
        # 仅选定默认模型——空 models 合法(执行时跟随实例列表首个)。
        if e.get("type") == "cline-sdk" and eid != "cline":
            if not (cfg.get("model_id") or cfg["models"]):
                return (f"执行器 {eid}(cline-sdk) 需配置模型：顶层默认 model_id 或 models "
                        "列表至少一项——空模型会被 runner 拒绝。")
            mid = (cfg.get("model_id") or "").strip()
            if mid:
                hits = [m for m in cfg["models"]
                        if mid in (m["model"], m["name"], m["id"])]
                if cfg["models"] and not hits:
                    return (f"执行器 {eid} 顶层默认 model_id={mid!r} 未命中任何 models 条目"
                            "(model/name/id)——实际执行模型将与 UI 展示不一致")
            for m in cfg["models"]:
                if not str(m["url"]).startswith(("http://", "https://")):
                    return (f"执行器 {eid} 模型 {m['name']} url 非法: {m['url']!r}"
                            "(须 http/https)")
        if e.get("default"):
            defaults += 1
    if defaults > 1:
        return "只能有一个默认执行器"
    return None


def _mask(entries: list[dict]) -> list[dict]:
    out = []
    for e in entries:
        cfg = dict(e.get("config") or {})
        for k in _SECRET_KEYS:
            if cfg.get(k):
                cfg[k] = "******"
        cfg["models"] = [
            {**m, "apiKey": "******"} if m.get("apiKey") else m
            for m in cfg.get("models") or []
        ]
        out.append({**e, "config": cfg})
    return out


def _merge_secret_models(entries: list, old: dict) -> None:
    """前端提交 ****** 视为不变: 与已存密钥合并。"""
    for e in entries:
        old_models = {m.get("name"): m for m in ((old.get(e.get("id")) or {}).get("config") or {}).get("models") or []}
        for m in (e.get("config") or {}).get("models") or []:
            if m.get("apiKey") == "******":
                prev = old_models.get(m.get("name")) or {}
                if prev.get("apiKey"):
                    m["apiKey"] = prev["apiKey"]


def _get_runner(path: str, timeout: float = 5.0) -> Optional[dict]:
    try:
        with urllib.request.urlopen(f"{RUNNER_BASE_URL}{path}", timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception:  # noqa: BLE001
        return None


# ── 路由 ──

@router.get("/agent/executors")
async def list_executors():
    """注册表（脱敏）+ runner 运行态（若可达）。内置 cline 模型面=实例实时投影。"""
    entries = _normalize(load_executors())
    for e in entries:
        if e.get("id") == "cline" and e.get("type") == "cline-sdk":
            live = _builtin_cline_models()
            if live:
                e.setdefault("config", {})["models"] = live
    runtime = _get_runner("/health")
    return ok({
        "executors": _mask(entries),
        "runtime": {"reachable": bool(runtime)} if runtime else {"reachable": False},
        "runnerBaseUrl": RUNNER_BASE_URL,
    })


@router.put("/agent/executors")
async def put_executors(request: Request, background: BackgroundTasks):
    """保存注册表（全量覆盖）→ 后台触发 runner 热刷新。

    刷新必须脱离本请求：runner 刷新时会回调 architect /runtime 拉配置，
    同步执行会让 architect 阻塞在 runner 上、runner 又阻塞在 architect
    上（互等→6s 超时→runner 静默回退内置池）。
    """
    body = await request.json()
    entries = body.get("executors")
    if not isinstance(entries, list):
        return err(400, "executors 必须为列表")
    # 与已存密钥合并（前端提交 ****** 视为不变）
    _normalize(entries)
    old = {e.get("id"): e for e in load_executors()}
    for e in entries:
        cfg = e.get("config") or {}
        old_cfg = (old.get(e.get("id")) or {}).get("config") or {}
        for k in _SECRET_KEYS:
            if cfg.get(k) == "******" and old_cfg.get(k):
                cfg[k] = old_cfg[k]
    _merge_secret_models(entries, old)
    # 内嵌执行器保护: cline(architect 自主模式 sidecar)不可删除
    if "cline" in old and "cline" not in {e.get("id") for e in entries}:
        return err(400, "cline 为内嵌执行器(architect 自主模式), 不可删除")
    msg = _validate(entries)
    if msg:
        return err(400, msg)
    for e in entries:
        if e.get("id") == "cline" and e.get("type") == "cline-sdk":
            # 内置 cline 模型面=实例实时投影: 不落盘(防快照过期复活; 执行时注入)
            if isinstance(e.get("config"), dict):
                e["config"]["models"] = []
    save_executors(entries)
    return ok({"saved": len(entries), "updatedAt": _ts()})


@router.post("/agent/executors/{eid}/capability-probe")
async def start_capability_probe(eid: str):
    """启动执行器能力探测(环节十二b): 5 探针标定套件, 异步后台执行。

    重复启动 → 409; 结果写回注册表 config(tierProbed/probeScore/probeDetail/
    probedAt/probedModel), GET 查询进度。"""
    entries = load_executors()
    entry = next((e for e in entries if e.get("id") == eid), None)
    if not entry:
        return err(404, f"执行器不存在: {eid}")
    if eid in _CAP_PROBE_RUNNING:
        return err(409, "该执行器探测进行中, 请等待完成")
    _CAP_PROBE_RUNNING.add(eid)

    def _persist(fields: dict) -> None:
        try:
            entries = load_executors()
            for e in entries:
                if e.get("id") == eid:
                    e.setdefault("config", {}).update(fields)
                    break
            save_executors(entries)
        except Exception:  # noqa: BLE001
            logger.warning("[capability-probe] persist failed: %s", eid)

    async def _task():
        from ..agent.execution.probes import run_capability_probe
        try:
            await run_capability_probe(entry, _runner_transport, _persist)
        except Exception as e:  # noqa: BLE001
            logger.exception("[capability-probe] %s failed", eid)
            _persist({"probeDetail": f"探测异常: {e}"})
        finally:
            _CAP_PROBE_RUNNING.discard(eid)

    asyncio.create_task(_task())
    return ok({"executorId": eid, "started": True,
               "summary": "能力探测已启动(5 探针, 预计数~十几分钟), GET 同路径查进度"})


@router.get("/agent/executors/{eid}/capability-probe")
async def capability_probe_status(eid: str):
    """探测结果/进度查询; needsReprobe = 探测后模型配置已变更。"""
    entry = next((e for e in load_executors() if e.get("id") == eid), None)
    if not entry:
        return err(404, f"执行器不存在: {eid}")
    cfg = entry.get("config") or {}
    probed_model = str(cfg.get("probedModel") or "")
    return ok({
        "executorId": eid,
        "running": eid in _CAP_PROBE_RUNNING,
        "tierProbed": str(cfg.get("tierProbed") or ""),
        "probeScore": cfg.get("probeScore"),
        "probeDetail": str(cfg.get("probeDetail") or ""),
        "probedAt": cfg.get("probedAt"),
        "needsReprobe": bool(probed_model and
                             probed_model != str(cfg.get("model_id") or "")),
    })


@router.post("/agent/executors/probe")
async def probe_executor(request: Request):
    """单条配置探活：本地可探的（opencode 端口/serve url/cline sidecar 文件）直接探，
    会话型执行器经本地进程/端口探测。"""
    body = await request.json()
    entry = body.get("entry") or {}
    etype, cfg = entry.get("type"), entry.get("config") or {}
    try:
        if etype in ("opencode", "serve-generic"):
            url = (cfg.get("base_url") or f"http://127.0.0.1:{cfg.get('base_port', 3478)}").rstrip("/")
            path = "/global/health" if etype == "opencode" else "/health"
            try:
                with urllib.request.urlopen(f"{url}{path}", timeout=3) as r:
                    return ok({"status": "ok" if r.status == 200 else "fail",
                               "detail": f"{url} HTTP {r.status}"})
            except Exception as e:  # noqa: BLE001
                # 连接拒绝 = serve 未运行: auto_start 开启属预期状态(执行时自动拉起),
                # 单独标记 stopped 而非 fail, 前端以中性样式展示
                refused = "Connection refused" in str(e) or isinstance(
                    getattr(getattr(e, "reason", None), "errno", None), int) and getattr(
                    getattr(e, "reason", None), "errno", 0) == 111
                if refused and etype == "opencode" and cfg.get("auto_start"):
                    return ok({"status": "stopped", "detail": f"{url} 未运行",
                               "note": "auto_start 已开启——执行时自动拉起，无需手动启动"})
                raise
        if etype == "cline-sdk":
            script = str(cfg.get("sidecar_script") or "").strip()
            engine_note = ""
            if not script:
                # 引擎解析链与任务下发同源(exec_bridge.executor_hint_by_id):
                # 显式配置 > 引擎默认版本 > 仓库内置 dist
                try:
                    from .cline_engines import resolve_engine, list_engines
                    eng = resolve_engine()
                    if eng:
                        script = eng["script"]
                        engine_note = f"；引擎 {eng['version']}（存储隔离 {eng['dataDir']}）"
                    else:
                        installed = list_engines()
                        if installed:
                            engine_note = ("；已装引擎 "
                                           + "/".join(e["version"] for e in installed)
                                           + " 但无有效默认——回退仓库内置 sidecar")
                except Exception:  # noqa: BLE001
                    pass
            script = script or _default_sidecar_path()
            exists = os.path.isfile(script)
            detail = f"sidecar: {script} {'存在' if exists else '缺失（需 npm run build -w packages/cline-sidecar）'}" + engine_note
            # node 版本门槛（@cline/core 硬性要求 >=22）
            node_ver = ""
            try:
                out = subprocess.run(["node", "--version"], capture_output=True,
                                     text=True, timeout=10)
                node_ver = (out.stdout or "").strip()
            except Exception:  # noqa: BLE001
                pass
            try:
                major = int(node_ver.lstrip("v").split(".")[0]) if node_ver else 0
            except ValueError:  # noqa: BLE001
                major = 0
            if node_ver and 0 < major < 22:
                return ok({"status": "fail",
                           "detail": f"{detail}；node {node_ver} 过低（@cline/core 要求 >=22）"})
            if node_ver:
                detail += f"；node {node_ver}"
            return ok({"status": "ok" if exists else "fail", "detail": detail})
        if etype == "cli":
            import shutil
            cmd = (cfg.get("command") or "").split()
            binpath = shutil.which(cmd[0]) if cmd else None
            return ok({"status": "ok" if binpath else "fail",
                       "detail": f"{cmd[0] if cmd else '?'}: {binpath or '未找到'}"})
        if etype == "remote-agent":
            url = (cfg.get("agent_url") or "").rstrip("/")
            if not url:
                return ok({"status": "fail", "detail": "缺少 agent_url（远端 opencode serve 地址）"})
            with urllib.request.urlopen(f"{url}/global/health", timeout=5) as r:
                return ok({"status": "ok" if r.status == 200 else "fail",
                           "detail": f"{url} HTTP {r.status}"})
        if etype == "codex-server":
            import shutil as _sh
            binpath = _sh.which(cfg.get("codex_bin", "codex"))
            return ok({"status": "ok" if binpath else "fail", "detail": f"codex: {binpath or '未找到'}"})
        return ok({"status": "ok", "detail": f"type={etype} 无需探活"})
    except Exception as e:  # noqa: BLE001
        return ok({"status": "fail", "detail": str(e),
                   "note": "serve 未运行属正常（执行时自动拉起）"})


def _bin_version(bin_name: str, args: tuple = ("--version",)) -> str:
    """二进制存在则取版本(截断), 不存在返回空串。"""
    path = shutil.which(bin_name)
    if not path:
        return ""
    try:
        out = subprocess.run([path, *args], capture_output=True, text=True, timeout=15)
        return (out.stdout or out.stderr).strip().splitlines()[0][:80] if (out.stdout or out.stderr) else path
    except Exception:  # noqa: BLE001
        return path


INSTALL_CMDS = {
    "opencode": "npm install -g opencode-ai",
    "codex": "npm install -g @openai/codex",
}


def _env_detect() -> dict:
    """检测已适配的 coding agent 安装状态(未适配类型不检)。

    opencode/codex: which + --version; cline: node + 内置 sidecar 产物 + 引擎版本。
    """
    sidecar = _default_sidecar_path()
    node = _bin_version("node")
    oc = _bin_version("opencode")
    cx = _bin_version("codex")
    engines: list = []
    engine_default = ""
    try:
        from .cline_engines import list_engines, default_version
        engines = [e["version"] for e in list_engines()]
        engine_default = default_version()
    except Exception:  # noqa: BLE001
        pass
    return {
        "opencode": {"installed": bool(oc), "version": oc,
                     "installCmd": INSTALL_CMDS["opencode"]},
        "codex": {"installed": bool(cx), "version": cx,
                  "installCmd": INSTALL_CMDS["codex"]},
        "cline": {"installed": bool(node) and os.path.isfile(sidecar),
                  "version": node, "sidecar": sidecar,
                  "sidecarExists": os.path.isfile(sidecar),
                  "engines": engines, "engineDefault": engine_default,
                  "installCmd": "npm run build -w packages/cline-sidecar（topoOne-ui 仓库根）"},
    }


@router.get("/agent/executors/env")
async def executors_env():
    """环境检测: 当前安装了哪些已适配 coding agent。"""
    return ok(_env_detect())


@router.post("/agent/executors/install")
async def install_executor(request: Request):
    """一键辅助安装(同步执行, 长超时; 返回输出尾部)。"""
    body = await request.json()
    agent = str(body.get("agent") or "").strip()
    if agent not in ("opencode", "codex", "cline"):
        return err(400, "仅支持 opencode/codex/cline")
    if agent == "cline":
        # sidecar 随仓库分发: 定位 topoOne-ui 仓库根执行 workspace 构建
        root = ""
        probe = os.path.expanduser("~/topoCodeProj/topoOne-ui")
        if os.path.isfile(os.path.join(probe, "package.json")):
            root = probe
        if not root:
            return err(400, "未定位到 topoOne-ui 仓库根, 请手动执行: npm run build -w packages/cline-sidecar")
        cmd = ["npm", "run", "build", "-w", "packages/cline-sidecar"]
    else:
        cmd = ["npm", "install", "-g", "opencode-ai" if agent == "opencode" else "@openai/codex"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=root or None)
        tail = "\n".join(((out.stdout or "") + (out.stderr or "")).strip().splitlines()[-8:])
        okv = out.returncode == 0
    except subprocess.TimeoutExpired:
        return ok({"status": "fail", "detail": "安装超时(300s), 请检查网络后重试或手动安装"})
    except Exception as e:  # noqa: BLE001
        return ok({"status": "fail", "detail": str(e)})
    return ok({"status": "ok" if okv else "fail",
               "detail": ("安装完成" if okv else f"退出码 {out.returncode}") + (f"\n{tail}" if tail else "")})


@router.post("/agent/executors/start")
async def start_executor(request: Request):
    """手动拉起执行器(opencode serve)。cwd=项目源码目录(前端传入, 不可改)。"""
    body = await request.json()
    entry = body.get("entry") or {}
    if entry.get("type") != "opencode":
        return err(400, "仅 opencode 执行器支持手动拉起(其余类型在执行时按需启动)")
    return ok(_start_opencode_serve(entry.get("config") or {},
                                    str(body.get("cwd") or "").strip()))


@router.post("/agent/executors/stop")
async def stop_executor(request: Request):
    """关闭手动拉起的 opencode serve。

    安全: 仅精确匹配 "opencode serve --port <port>" 特征的进程, 严禁误杀。
    """
    body = await request.json()
    entry = body.get("entry") or {}
    if entry.get("type") != "opencode":
        return err(400, "仅 opencode 执行器支持此操作")
    port = int((entry.get("config") or {}).get("base_port") or 3478)
    pattern = f"opencode serve --port {port}"
    try:
        pg = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True, timeout=10)
        pids = [x for x in (pg.stdout or "").split() if x.strip().isdigit()]
    except Exception as e:  # noqa: BLE001
        return ok({"status": "fail", "detail": str(e)})
    if not pids:
        return ok({"status": "fail", "detail": f"未发现运行中的 {pattern} 进程"})
    killed = []
    for pid in pids:
        try:
            os.kill(int(pid), 15)
            killed.append(pid)
        except Exception:  # noqa: BLE001
            pass
    return ok({"status": "ok", "detail": f"已停止 {len(killed)} 个进程(port={port})"})


@router.post("/agent/executors/models/detect")
async def detect_executor_models(request: Request):
    """检测执行器可用模型(opencode: serve /config 的 provider×models)。"""
    body = await request.json()
    entry = body.get("entry") or {}
    if entry.get("type") != "opencode":
        return err(400, "仅 opencode 执行器支持模型检测")
    return ok(_detect_opencode_models(entry.get("config") or {},
                                      str(body.get("cwd") or "").strip()))


def _probe_llm_model(url: str, model: str, api_key: str = "") -> dict:
    """模型连通性测试: OpenAI 兼容。三级探测——
    ① GET /models(廉价) ② 流式 1-token 对话(Cline 网关强制 stream:true, 关键兼容面)
    ③ 非流式对话兜底。返回 detail 标注流式兼容性。

    模型拣择匹配(llama-server 等 OpenAI 兼容服务 /models 返回裸 id,
    白名单存 opencode 的 provider/model 全名): 全名 → 裸名 → 段后缀 三级匹配。
    """
    base = (url or "").rstrip("/")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if not base:
        return {"status": "fail", "detail": "缺少模型服务 url"}

    def _match(mid: str) -> bool:
        low, full, b = mid.lower(), model.lower(), model.rsplit("/", 1)[-1].lower()
        return low == full or low == b or low.endswith("/" + b) or low.rsplit("/", 1)[-1] == b

    def _pick(cands: list[str]) -> str:
        """四级拣择: 全名/裸名精确 → 段后缀 → 子串(兼容 gguf 路径/别名)。"""
        full, b = model.lower(), model.rsplit("/", 1)[-1].lower()
        for mid in cands:
            if mid.lower() in (full, b):
                return mid
        for mid in cands:
            low = mid.lower()
            if low.endswith("/" + b) or low.rsplit("/", 1)[-1] == b:
                return mid
        for mid in cands:
            if b in mid.lower():
                return mid
        return ""

    def _stream_probe() -> tuple[bool, str]:
        """流式兼容探测: stream:true + max_tokens=1。"""
        try:
            payload = json.dumps({"model": model.rsplit("/", 1)[-1],
                                  "messages": [{"role": "user", "content": "ping"}],
                                  "max_tokens": 1, "stream": True}).encode()
            req = urllib.request.Request(
                f"{base}/chat/completions", data=payload, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=20) as r:
                ctype = (r.headers or {}).get("Content-Type", "")
                head = r.read(512).decode("utf-8", "replace")
                if "text/event-stream" in ctype or head.startswith("data:"):
                    return True, f"{base} 流式 HTTP {r.status}"
                # 200 但非 SSE: 网关不支持流式（Cline 路径会失败）
                return False, f"{base} HTTP {r.status} 但非 SSE 流(不支持 stream:true?)"
        except Exception as e:  # noqa: BLE001
            return False, f"流式失败: {str(e)[:150]}"

    try:
        req = urllib.request.Request(f"{base}/models", headers=headers)
        with urllib.request.urlopen(req, timeout=6) as r:
            body = r.read().decode("utf-8", "replace")[:16384]
            cands: list[str] = []
            try:
                payload = json.loads(body)
                entries = payload.get("data") or payload.get("models") or []
                for m in entries:
                    if isinstance(m, dict):
                        cands.extend(str(m.get(k) or "") for k in ("id", "name", "model") if m.get(k))
                    elif isinstance(m, str):
                        cands.append(m)
            except Exception:  # noqa: BLE001
                pass
            if cands:
                matched = _pick(cands)
                suffix = f"(命中 {matched})" if matched else f"(列表未见 {model}, 仍可达)"
            else:
                suffix = "" if (model in body or model.rsplit("/", 1)[-1] in body) else f"(列表未见 {model}, 仍可达)"
            stream_ok, stream_detail = _stream_probe()
            detail = f"{base}/models HTTP {r.status}{suffix} | {stream_detail}"
            if not stream_ok:
                return {"status": "fail",
                        "detail": detail,
                        "note": "Cline 网关强制流式(stream:true)；可改用 Ollama 原生 provider 提升兼容性"}
            return {"status": "ok", "detail": detail}
    except Exception as e1:  # noqa: BLE001
        try:
            payload = json.dumps({"model": model.rsplit("/", 1)[-1], "messages": [
                {"role": "user", "content": "ping"}], "max_tokens": 1}).encode()
            req = urllib.request.Request(
                f"{base}/chat/completions", data=payload, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=20) as r:
                return {"status": "ok", "detail": f"{base}/chat/completions HTTP {r.status}"}
        except Exception as e2:  # noqa: BLE001
            return {"status": "fail", "detail": f"/models: {e1} | /chat/completions: {e2}"}


@router.post("/agent/executors/model-probe")
async def model_probe(request: Request):
    """实例内模型连通性测试。Body: { url, model, apiKey?, entry? }。

    opencode 执行器且 url 为空(内置目录/登录态 provider 无直连面) →
    opencode 侧静态探活(目录+凭据, 连接本就由 opencode 负责);
    其余(带 url 自建模型/其它类型)保持 OpenAI 兼容直连探测。
    """
    body = await request.json() or {}
    url = str(body.get("url") or "").strip()
    model = str(body.get("model") or "").strip()
    if not model:
        return err(400, "缺少 model")
    entry = body.get("entry") or {}
    if entry.get("type") == "opencode" and not url:
        return ok(_probe_opencode_model(entry.get("config") or {},
                                        str(body.get("cwd") or "").strip(), model))
    return ok(_probe_llm_model(url, model, str(body.get("apiKey") or "")))


@router.get("/agent/executors/runtime")
async def runtime_executors():
    """runner 拉取面（内部）：解析后的完整注册表（不脱敏，含密钥）。"""
    entries = load_executors()
    enabled = [e for e in entries if e.get("enabled", True)]
    return ok({"executors": enabled, "updatedAt": _ts()})


def _default_sidecar_path() -> str:
    # arch_routes → topoone_app_architect → architect → apps → 仓库根
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
    return os.path.join(root, "..", "packages", "cline-sidecar", "dist", "index.js")
