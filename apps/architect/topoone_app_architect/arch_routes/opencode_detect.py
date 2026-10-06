"""opencode serve 拉起 + 探测面(全量模型目录/内置代理)—— 自 agent_executors 拆分(§8.2)。

探测链(serve 就绪后逐级降级, 任一缺失不影响其余):
- GET /config/providers → 全量 provider×models(models.dev 内置 + 用户配置 + env 密钥)
- GET /provider         → connected[] 与 limit{context,output} 元数据
- GET /agent            → 内置(build/plan/general/…)与用户自定义代理清单
- GET /config           → 旧版兜底(仅用户配置 provider; 1.x 早期无前两者)
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.parse
import urllib.request


def _oc_bin() -> str:
    return shutil.which("opencode") or "opencode"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """禁跟随重定向: 端口扫描时 302 必须视为"不是 opencode"。

    实测: 同数据目录下其它工具(Java jar :3491)对 /global/health 返回 302,
    urllib 默认自动跟随 → 落到 200/PNG, 被误判为 opencode serve。
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: N802
        return None


_OPENER_NORED = urllib.request.build_opener(_NoRedirect)


def _oc_ready(port: int) -> bool:
    """真就绪 = /global/health 直返 200(不跟随重定向) 且 /config 为合法 JSON。"""
    try:
        with _OPENER_NORED.open(f"http://127.0.0.1:{port}/global/health", timeout=3) as r:
            if r.status != 200:
                return False
    except Exception:  # noqa: BLE001
        return False
    try:
        with _OPENER_NORED.open(f"http://127.0.0.1:{port}/config", timeout=3) as r:
            json.loads(r.read().decode("utf-8"))
        return True
    except Exception:  # noqa: BLE001
        return False


def _start_opencode_serve(cfg: dict, cwd: str = "") -> dict:
    """手动拉起 opencode serve(脱离本进程会话, 与 runner 同款命令/日志布局)。

    端口从 base_port 起探活分配(健康端口视为占用, 跳过); 已在运行则直接返回。
    """
    base = int(cfg.get("base_port") or 3478)
    for off in range(0, 24):
        if _oc_ready(base + off):
            return {"status": "ok", "port": base + off,
                    "url": f"http://127.0.0.1:{base + off}",
                    "note": "serve 已在运行"}
    port = base
    for off in range(0, 24):
        if not _oc_ready(base + off):
            port = base + off
            break
    log_dir = os.path.join(os.path.expanduser("~"), ".topocode", "runner")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f"opencode-serve-{port}.log")
    log = open(log_path, "ab")  # noqa: SIM115
    proc = subprocess.Popen(
        [_oc_bin(), "serve", "--port", str(port), "--hostname", "127.0.0.1"],
        cwd=cwd or cfg.get("cwd") or os.path.expanduser("~"),
        stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    import time as _t
    for _ in range(25):
        if _oc_ready(port):
            return {"status": "ok", "port": port, "url": f"http://127.0.0.1:{port}",
                    "pid": proc.pid, "log": log_path, "note": "serve 已拉起"}
        if proc.poll() is not None:
            break
        _t.sleep(1.0)
    try:
        proc.kill()
    except Exception:  # noqa: BLE001
        pass
    return {"status": "fail", "detail": f"serve 启动失败 port={port}（见 {log_path}）"}


def _parse_oc_config(cfg_json: dict) -> list:
    """/config → 模型条目[{name, model, url, kind}](kind: local/cloud)。

    只取带 baseURL 的 provider(自建/局域网/显式配置); kind 按地址性质划分。
    """
    out = []
    for prov, pc in (cfg_json.get("provider") or {}).items():
        base = ((pc.get("options") or {}).get("baseURL") or "").rstrip("/")
        models = pc.get("models") or {}
        if not base or not models:
            continue
        host = urllib.parse.urlparse(base).hostname or ""
        private = host in ("localhost", "127.0.0.1") or host.startswith("192.168.")             or host.startswith("10.") or host.startswith("172.")
        for m in models:
            out.append({"name": m, "model": f"{prov}/{m}", "url": base,
                        "kind": "local" if private else "cloud"})
    return out


def _get_json(url: str, timeout: float = 10.0):
    """GET URL → JSON(任意类型); 失败返回 None(探测面缺失由调用方降级)。"""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _parse_oc_providers(providers_json, provider_list_json) -> tuple:
    """opencode 全量可用模型目录 → (条目清单, 目录全量计数)。

    数据源(二者缺一可, /config/providers 为主):
    - GET /config/providers → providers[].{id, source(env|config|custom|api),
      key?, options.baseURL, models{}}——models.dev 内置目录 + 用户配置 + env 密钥
    - GET /provider         → {connected[], all[].models{}.limit{context,output}}

    过滤降噪(目录全量数百条): 只保留 已连接 ∪ 有密钥 ∪ source=config 的
    provider; 其余折叠进 total/omitted 计数(前端可感知)。
    条目 name/model/url/kind 与旧 /config 解析同形(白名单三级匹配兼容),
    另附 source/authed/connected/context/output 元数据。
    """
    connected: set = set()
    limits: dict = {}
    if isinstance(provider_list_json, dict):
        connected = set(provider_list_json.get("connected") or [])
        for prov in provider_list_json.get("all") or []:
            if not isinstance(prov, dict):
                continue
            pid = str(prov.get("id") or "")
            for mid, m in (prov.get("models") or {}).items():
                lim = (m or {}).get("limit") or {}
                if isinstance(lim, dict) and (lim.get("context") or lim.get("output")):
                    limits[(pid, str(mid))] = {"context": int(lim.get("context") or 0),
                                               "output": int(lim.get("output") or 0)}
    if isinstance(providers_json, dict):
        provs = providers_json.get("providers") or []
    else:
        provs = providers_json or []

    out: list = []
    total = 0
    for pc in provs:
        if not isinstance(pc, dict):
            continue
        prov = str(pc.get("id") or "")
        models = pc.get("models") or {}
        if not prov or not models:
            continue
        total += len(models)
        source = str(pc.get("source") or "")
        is_conn = prov in connected
        # 降噪白名单: 已连接/有密钥/用户显式配置 三者其一
        if not (is_conn or pc.get("key") or source == "config"):
            continue
        base = ((pc.get("options") or {}).get("baseURL") or "").rstrip("/")
        host = urllib.parse.urlparse(base).hostname or "" if base else ""
        private = host in ("localhost", "127.0.0.1") or host.startswith("192.168.")             or host.startswith("10.") or host.startswith("172.")
        for mid in models:
            entry = {"name": str(mid), "model": f"{prov}/{mid}", "url": base,
                     "kind": "local" if (base and private) else "cloud",
                     "source": source or ("config" if base else "builtin"),
                     "authed": bool(pc.get("key")) or source == "config" or is_conn,
                     "connected": is_conn}
            lim = limits.get((prov, str(mid)))
            if lim:
                entry["context"] = lim["context"]
                entry["output"] = lim["output"]
            out.append(entry)
    out.sort(key=lambda e: e["model"].lower())
    return out, total


def _parse_oc_agents(agents_json) -> list:
    """GET /agent → 代理条目[{name, mode, builtIn, description, model}]。

    builtIn 置前; model 拼 providerID/modelID 全名(与白名单/job.model 同形)。
    内置代理(build/plan/general/…)与用户自定义(.opencode/agent/*)同面返回。
    """
    out = []
    for a in agents_json or []:
        if not isinstance(a, dict):
            continue
        name = str(a.get("name") or "")
        if not name:
            continue
        m = a.get("model") or {}
        model = ""
        if isinstance(m, dict) and m.get("modelID"):
            pid = str(m.get("providerID") or "")
            model = f"{pid}/{m['modelID']}" if pid else str(m["modelID"])
        out.append({"name": name,
                    "mode": str(a.get("mode") or ""),
                    "builtIn": bool(a.get("builtIn")),
                    "description": str(a.get("description") or ""),
                    "model": model})
    out.sort(key=lambda x: (not x["builtIn"], x["name"].lower()))
    return out


def _detect_opencode_models(cfg: dict, cwd: str = "") -> dict:
    """检测 opencode 可用模型与内置代理: ensure serve → 探测链逐级降级。

    - GET /config/providers → 全量 provider×models(内置目录+用户配置+env 密钥)
    - GET /provider         → connected/limit 元数据合并
    - GET /agent            → 内置/自定义代理清单
    - GET /config           → 旧版兜底(仅用户配置 provider; 1.x 早期无前两者)
    任一探测面缺失不影响其余; 全部缺失时报 /config 重试失败。
    """
    started = _start_opencode_serve(cfg, cwd)
    if started.get("status") != "ok":
        return started
    port = started["port"]
    base_url = f"http://127.0.0.1:{port}"

    providers_json = _get_json(f"{base_url}/config/providers")
    provider_list_json = _get_json(f"{base_url}/provider")
    if providers_json or provider_list_json:
        models, total = _parse_oc_providers(providers_json, provider_list_json)
        # /config/providers 缺失(旧版) → /provider.all 形状兼容, 同解析器复用
        if not providers_json and provider_list_json:
            models, total = _parse_oc_providers(
                {"providers": provider_list_json.get("all") or []},
                provider_list_json)
    else:
        cfg_json = None
        last_err = ""
        raw = b""
        for _ in range(3):
            try:
                with urllib.request.urlopen(f"{base_url}/config", timeout=10) as r:
                    raw = r.read()
                cfg_json = json.loads(raw.decode("utf-8"))
                break
            except Exception as e:  # noqa: BLE001
                head = f"; 头字节 {raw[:8].hex()}" if raw else ""
                last_err = f"{e}{head}"
                import time as _t
                _t.sleep(1.0)
        if cfg_json is None:
            return {"status": "fail", "detail": f"/config 读取失败(重试 3 次): {last_err}"}
        models, total = _parse_oc_config(cfg_json), 0

    agents = _parse_oc_agents(_get_json(f"{base_url}/agent"))
    note = str(started.get("note") or "")
    omitted = max(total - len(models), 0)
    if omitted:
        note = (f"{note}; " if note else "") \
            + f"另有 {omitted} 个未配置密钥的内置目录模型未列出"
    return {"status": "ok", "port": port, "models": models, "agents": agents,
            "total": total, "omitted": omitted, "note": note}


def _probe_opencode_model(cfg: dict, cwd: str, model: str) -> dict:
    """opencode 侧静态探活(零 token): 模型在目录 + provider 有凭据。

    url 为空的白名单条目(内置目录/登录态 provider)无直连探测面——连接由
    opencode 侧负责(执行时以其自身配置调用), 故探「opencode 是否就绪」:
    - 模型全名(prov/mid, 兼容裸名)在 /config/providers 目录中
    - provider 已连接 ∪ 有密钥 ∪ source=config(与 _parse_oc_providers 同判据)
    密钥失效等运行期问题由真实执行的 job.last_error 暴露(静态检查无法廉价验证)。
    """
    started = _start_opencode_serve(cfg, cwd)
    if started.get("status") != "ok":
        return started
    base_url = f"http://127.0.0.1:{started['port']}"
    providers_json = _get_json(f"{base_url}/config/providers")
    provider_list_json = _get_json(f"{base_url}/provider")
    connected: set = set(provider_list_json.get("connected") or []) \
        if isinstance(provider_list_json, dict) else set()
    provs = (providers_json.get("providers")
             if isinstance(providers_json, dict) else providers_json) or []

    full = model.strip().lower()
    mid_req = full.split("/", 1)[-1]
    prov_req = full.split("/", 1)[0] if "/" in full else ""

    def _provider_of(pred) -> str:
        for pc in provs:
            if not isinstance(pc, dict):
                continue
            pid = str(pc.get("id") or "")
            mids = {str(m).lower() for m in (pc.get("models") or {})}
            if pred(pid, mids):
                return pid
        return ""

    # 三级匹配(与白名单拣择同形): 全名精确(prov+mid) → 裸名(任一 provider)
    hit_prov = ""
    if prov_req:
        hit_prov = _provider_of(lambda pid, mids: pid.lower() == prov_req
                                and mid_req in mids)
    if not hit_prov:
        hit_prov = _provider_of(lambda pid, mids: mid_req in mids)
    if not hit_prov:
        return {"status": "fail",
                "detail": f"模型 {model} 不在 opencode 目录(opencode.json 未配置或 provider 未启用)"}

    hit_pc = next((pc for pc in provs if isinstance(pc, dict)
                   and str(pc.get("id") or "") == hit_prov), {})
    source = str(hit_pc.get("source") or "")
    has_key = bool(hit_pc.get("key"))
    is_conn = hit_prov in connected
    if not (is_conn or has_key or source == "config"):
        return {"status": "fail",
                "detail": f"provider {hit_prov} 未配置密钥"
                          "(opencode auth login 或 opencode.json provider 段)"}
    how = "已连接" if is_conn else ("有密钥" if has_key else "已显式配置")
    return {"status": "ok",
            "detail": f"opencode 侧已就绪(provider={hit_prov}, {how}, 模型={mid_req})"}
