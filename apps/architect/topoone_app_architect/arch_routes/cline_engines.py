"""cline SDK 引擎版本管理 — 多版本共存隔离。

隔离模型(2026-09-19 裁决):
  - 每版本自包含目录 ~/.topocode/cline/engines/<version>/
      dist/          sidecar 编译产物(仓库构建拷贝, 版本间只差依赖)
      node_modules/  该版本 @cline/sdk 及传递依赖(npm 精确锁版)
      package.json   运行时清单(@cline/sdk 精确版本)
      data/          该版本专属存储(TOPOCODE_CLINE_DATA_DIR 注入 → 会话/设置隔离)
      .engine.json   元数据 {version, installedAt, node}
  - runner sidecar 单例按 (node, script, data_dir) 键 → 不同版本天然独立进程
  - 数据目录按版本隔离 → 会话不跨版本(sessionRef 复活仅本版本内)
  - 默认版本 arch_collab_config["cline.engineDefault"]; 空=回退仓库内置 sidecar

优先级: 注册表显式 sidecar_script > 引擎默认版本 > 仓库内置 dist。
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import time
import urllib.request
from typing import Optional

from fastapi import APIRouter, Request

from .common import _ts, ok, err
from . import store

logger = logging.getLogger(__name__)

router = APIRouter()

CONFIG_KEY = "cline.engineDefault"
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[\w.]+)?$")
_NIGHTLY_RE = re.compile(r"-nightly\.")
# npm registry 版本清单查询(CLINE_NPM_REGISTRY 可覆盖: 镜像/离线源)
_REGISTRY_URL = (os.environ.get("CLINE_NPM_REGISTRY",
                                "https://registry.npmjs.org").rstrip("/")
                 + "/@cline/sdk")
# 版本清单缓存(registry 慢/断网不拖垮配置页)
_avail_cache: dict = {"ts": 0.0, "data": None}
_AVAIL_TTL = 300.0
_INSTALLING = False
_INSTALL_TIMEOUT = 600.0
from ..agent.governance.timeouts import get as _timeout_of
_BUILD_TIMEOUT = _timeout_of("build_engine")


def engines_root() -> str:
    return os.path.join(os.path.expanduser("~"), ".topocode", "cline", "engines")


def repo_root() -> str:
    # arch_routes → topoone_app_architect → architect → apps → 仓库根
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.."))


def sidecar_source_dir() -> str:
    return os.path.join(repo_root(), "packages", "cline-sidecar")


def repo_sidecar_dist() -> str:
    """仓库内置 sidecar 产物(回退链终点, 与 agent_executors._default_sidecar_path 一致)。"""
    return os.path.join(sidecar_source_dir(), "dist", "index.js")


def _valid_version(v: str) -> bool:
    """版本号白名单(防路径穿越: 引擎目录名即版本名)。"""
    return bool(_VERSION_RE.match(v or ""))


def engine_dir(version: str) -> str:
    return os.path.join(engines_root(), version)


def default_version() -> str:
    try:
        return str(store.CollabConfigStore.get(CONFIG_KEY, "") or "")
    except Exception:  # noqa: BLE001
        return ""


def verify_engine(version: str) -> dict:
    """单引擎健康检查: dist 产物 + 锁版依赖版本一致。"""
    d = engine_dir(version)
    missing = []
    if not os.path.isfile(os.path.join(d, "dist", "index.js")):
        missing.append("dist/index.js")
    sdk_pkg = os.path.join(d, "node_modules", "@cline", "sdk", "package.json")
    sdk_ver = ""
    if not os.path.isfile(sdk_pkg):
        missing.append("node_modules/@cline/sdk")
    else:
        try:
            with open(sdk_pkg, encoding="utf-8") as f:
                sdk_ver = str(json.load(f).get("version") or "")
            if sdk_ver != version:
                missing.append(f"@cline/sdk 版本不符(实际 {sdk_ver})")
        except Exception:  # noqa: BLE001
            missing.append("@cline/sdk package.json 不可读")
    meta = {}
    try:
        with open(os.path.join(d, ".engine.json"), encoding="utf-8") as f:
            meta = json.load(f)
    except Exception:  # noqa: BLE001
        pass
    return {"version": version, "ok": not missing, "missing": missing,
            "sdkVersion": sdk_ver, "installedAt": meta.get("installedAt"),
            "node": meta.get("node"), "dataDir": os.path.join(d, "data"),
            "script": os.path.join(d, "dist", "index.js")}


def list_engines() -> list[dict]:
    root = engines_root()
    if not os.path.isdir(root):
        return []
    out = []
    for name in sorted(os.listdir(root)):
        if not _valid_version(name) or not os.path.isdir(engine_dir(name)):
            continue
        out.append(verify_engine(name))
    return out


def resolve_engine() -> Optional[dict]:
    """默认引擎 → {version, script, dataDir}; 无有效默认返回 None(调用方回退仓库内置)。"""
    v = default_version()
    if not v or not _valid_version(v):
        return None
    info = verify_engine(v)
    if not info["ok"]:
        return None
    return {"version": v, "script": info["script"], "dataDir": info["dataDir"]}


def set_default_version(version: str) -> Optional[str]:
    """设置默认版本(须已安装且健康); 返回错误信息或 None。"""
    if not _valid_version(version):
        return f"非法版本号: {version!r}"
    if not os.path.isdir(engine_dir(version)):
        return f"引擎未安装: {version}"
    if not verify_engine(version)["ok"]:
        return f"引擎损坏, 不能设为默认: {version}"
    store.CollabConfigStore.set(CONFIG_KEY, version)
    return None


def available_versions(force: bool = False) -> dict:
    """npm registry 版本清单(稳定版, 按发布时间倒序)。缓存 5 分钟; 断网返回 error。"""
    now = time.time()
    if not force and _avail_cache["data"] and now - _avail_cache["ts"] < _AVAIL_TTL:
        return _avail_cache["data"]
    data: dict = {}
    try:
        req = urllib.request.Request(_REGISTRY_URL, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=_timeout_of("engine_inspect")) as r:
            payload = json.loads(r.read().decode("utf-8")[:2_000_000])
        times = payload.get("time") or {}
        vers = [v for v in payload.get("versions", {})
                if _VERSION_RE.match(v) and not _NIGHTLY_RE.search(v)]
        vers.sort(key=lambda v: times.get(v, ""), reverse=True)
        data = {"latest": str((payload.get("dist-tags") or {}).get("latest") or ""),
                "versions": vers[:15],
                "fetchedAt": _ts(), "registry": _REGISTRY_URL}
    except Exception as e:  # noqa: BLE001
        data = {"latest": "", "versions": [], "error": f"registry 不可达: {str(e)[:150]}",
                "registry": _REGISTRY_URL}
    _avail_cache["ts"] = now
    _avail_cache["data"] = data
    return data


def _node_version() -> str:
    try:
        out = subprocess.run(["node", "--version"], capture_output=True,
                             text=True, timeout=_timeout_of("engine_inspect"))
        return (out.stdout or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _ensure_repo_dist(log: list[str], rebuild: bool) -> Optional[str]:
    """确保仓库 sidecar dist 就绪(缺失或显式 rebuild 时执行 workspace 构建)。"""
    src = sidecar_source_dir()
    if not os.path.isdir(src):
        return f"未定位到 sidecar 源目录: {src}"
    if rebuild or not os.path.isfile(repo_sidecar_dist()):
        log.append("$ npm run build -w packages/cline-sidecar")
        try:
            out = subprocess.run(
                ["npm", "run", "build", "-w", "packages/cline-sidecar"],
                capture_output=True, text=True, timeout=_BUILD_TIMEOUT, cwd=repo_root())
        except subprocess.TimeoutExpired:
            return "仓库 sidecar 构建超时(300s)"
        except Exception as e:  # noqa: BLE001
            return f"仓库 sidecar 构建失败: {e}"
        tail = "\n".join(((out.stdout or "") + (out.stderr or "")).splitlines()[-6:])
        log.append(tail)
        if out.returncode != 0:
            return f"仓库 sidecar 构建失败(退出码 {out.returncode})\n{tail}"
    if not os.path.isfile(repo_sidecar_dist()):
        return f"sidecar 产物缺失: {repo_sidecar_dist()}"
    return None


def _tail(text: str, n: int = 8) -> str:
    return "\n".join((text or "").strip().splitlines()[-n:])


def install_engine(version: str, rebuild: bool = False) -> dict:
    """安装指定版本引擎: 仓库构建 → 拷贝 dist → npm 精确锁版装依赖 → 校验 → 元数据。

    首个安装的版本自动设为默认(回退链立刻有真实现)。"""
    global _INSTALLING
    if not _valid_version(version):
        return {"status": "fail", "detail": f"非法版本号: {version!r}"}
    if _INSTALLING:
        return {"status": "fail", "detail": "已有安装任务进行中, 请等待完成"}
    _INSTALLING = True
    log: list[str] = []
    try:
        d = engine_dir(version)
        build_err = _ensure_repo_dist(log, rebuild)
        if build_err:
            return {"status": "fail", "detail": build_err + "\n" + "\n".join(log)}
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
        os.makedirs(os.path.join(d, "data"), exist_ok=True)
        # dist 拷贝(版本间只差依赖; 会话存储/日志随引擎目录隔离)
        shutil.copytree(os.path.join(sidecar_source_dir(), "dist"),
                        os.path.join(d, "dist"))
        with open(os.path.join(d, "package.json"), "w", encoding="utf-8") as f:
            json.dump({
                "name": "@topo/cline-sidecar",
                "version": "0.1.0",
                "private": True,
                "type": "module",
                "main": "dist/index.js",
                "engines": {"node": ">=22"},
                "dependencies": {"@cline/sdk": version},  # 精确锁版(无 ^)
            }, f, indent=2)
        log.append(f"$ npm install --omit=dev (@cline/sdk@{version})")
        try:
            out = subprocess.run(
                ["npm", "install", "--omit=dev", "--no-audit", "--no-fund",
                 "--loglevel=error"],
                capture_output=True, text=True, timeout=_INSTALL_TIMEOUT, cwd=d)
        except subprocess.TimeoutExpired:
            shutil.rmtree(d, ignore_errors=True)
            return {"status": "fail", "detail": f"安装超时({_INSTALL_TIMEOUT:.0f}s), "
                    "请检查网络/镜像(CLINE_NPM_REGISTRY)后重试\n" + "\n".join(log)}
        except Exception as e:  # noqa: BLE001
            shutil.rmtree(d, ignore_errors=True)
            return {"status": "fail", "detail": f"npm 安装失败: {e}\n" + "\n".join(log)}
        log.append(_tail((out.stdout or "") + (out.stderr or "")))
        if out.returncode != 0:
            shutil.rmtree(d, ignore_errors=True)
            return {"status": "fail",
                    "detail": f"npm 安装失败(退出码 {out.returncode})——版本不存在或网络不可达\n"
                    + "\n".join(log)}
        info = verify_engine(version)
        if not info["ok"]:
            shutil.rmtree(d, ignore_errors=True)
            return {"status": "fail",
                    "detail": "安装后校验未过: " + ", ".join(info["missing"]) + "\n"
                    + "\n".join(log)}
        with open(os.path.join(d, ".engine.json"), "w", encoding="utf-8") as f:
            json.dump({"version": version, "installedAt": _ts(),
                       "node": _node_version()}, f, ensure_ascii=False, indent=2)
        note = ""
        if not default_version():
            set_default_version(version)
            note = "；已设为默认版本"
        logger.info("[cline-engines] installed %s (auto-default=%s)", version, bool(note))
        return {"status": "ok",
                "detail": f"引擎 {version} 安装完成{note}\n" + "\n".join(log),
                "engine": info, "defaultVersion": default_version()}
    finally:
        _INSTALLING = False


def remove_engine(version: str) -> dict:
    """移除引擎(数据目录随引擎一并删除)。默认版本: 仅当它是唯一引擎时可移除
    (同时清空默认 → 回退仓库内置 sidecar); 否则须先切换默认。"""
    if not _valid_version(version):
        return {"status": "fail", "detail": f"非法版本号: {version!r}"}
    if not os.path.isdir(engine_dir(version)):
        return {"status": "fail", "detail": f"引擎未安装: {version}"}
    installed = [e["version"] for e in list_engines()]
    if default_version() == version and len(installed) > 1:
        return {"status": "fail",
                "detail": f"{version} 是当前默认版本, 请先切换默认后再移除"}
    shutil.rmtree(engine_dir(version), ignore_errors=True)
    note = ""
    if default_version() == version:
        store.CollabConfigStore.set(CONFIG_KEY, "")
        note = "；已清空默认——回退仓库内置 sidecar"
    logger.info("[cline-engines] removed %s", version)
    return {"status": "ok", "detail": f"引擎 {version} 已移除(含会话数据){note}",
            "defaultVersion": default_version()}


# ── 路由(/agent/executors/cline/engines*) ──────────────────────────────────

@router.get("/agent/executors/cline/engines")
async def list_engines_route():
    """引擎清单(已装 + 可装版本 + 默认 + 仓库内置回退态)。"""
    repo_ok = os.path.isfile(repo_sidecar_dist())
    return ok({
        "installed": list_engines(),
        "defaultVersion": default_version(),
        "available": available_versions(),
        "node": _node_version(),
        "repoSidecar": {"path": repo_sidecar_dist(), "exists": repo_ok},
    })


@router.post("/agent/executors/cline/engines/detect")
async def detect_engines_route():
    """强制刷新可装版本清单(绕过缓存)。"""
    return ok({"available": available_versions(force=True),
               "installed": list_engines(), "node": _node_version()})


@router.post("/agent/executors/cline/engines/install")
async def install_engine_route(request: Request):
    """安装指定版本(同步执行, 长超时; 仓库构建 + npm 精确锁版)。Body: {version, rebuild?}"""
    body = await request.json() or {}
    version = str(body.get("version") or "").strip()
    result = install_engine(version, rebuild=body.get("rebuild") is True)
    if result.get("status") != "ok":
        return err(result.get("detail") or "install failed")
    return ok(result)


@router.post("/agent/executors/cline/engines/remove")
async def remove_engine_route(request: Request):
    """移除引擎(含会话数据)。Body: {version}"""
    body = await request.json() or {}
    result = remove_engine(str(body.get("version") or "").strip())
    if result.get("status") != "ok":
        return err(result.get("detail") or "remove failed")
    return ok(result)


@router.post("/agent/executors/cline/engines/default")
async def set_default_engine_route(request: Request):
    """设置执行器默认使用的引擎版本。Body: {version}"""
    body = await request.json() or {}
    msg = set_default_version(str(body.get("version") or "").strip())
    if msg:
        return err(msg)
    return ok({"defaultVersion": default_version(), "updatedAt": _ts()})
