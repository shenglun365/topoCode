"""cline SDK 引擎版本管理回归测试(多版本共存隔离)。

Run: cd <repo> && python -m pytest apps/architect/tests/test_cline_engines.py -q
"""
import json
import os
import pathlib
import sys
import types

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

import topoone_app_architect.ctx as C


def _setup(tmp_path, monkeypatch):
    data = str(tmp_path / "arch")
    monkeypatch.setenv("ARCH_DATA_DIR", data)
    C._db = None
    C._kb = None
    C._data_dir = None
    C._project_dbs.clear()
    C.reset_project(C._project_var.set(None))
    C.reset_req(C._req_var.set(None))
    C.setup(data_dir=data)


def _fake_engine(root, version, ok=True):
    """伪造已装引擎目录(dist+data+meta[+锁版依赖])。"""
    d = os.path.join(str(root), version)
    os.makedirs(os.path.join(d, "dist"), exist_ok=True)
    with open(os.path.join(d, "dist", "index.js"), "w") as f:
        f.write("// sidecar")
    os.makedirs(os.path.join(d, "data"), exist_ok=True)
    if ok:
        sdk = os.path.join(d, "node_modules", "@cline", "sdk")
        os.makedirs(sdk, exist_ok=True)
        with open(os.path.join(sdk, "package.json"), "w") as f:
            json.dump({"version": version}, f)
    with open(os.path.join(d, ".engine.json"), "w") as f:
        json.dump({"version": version, "installedAt": "t", "node": "v22.0.0"}, f)
    return d


# ── 版本号白名单(路径穿越防护) ────────────────────────────────────────

def test_version_sanitize():
    from topoone_app_architect.arch_routes import cline_engines as CE
    assert CE._valid_version("0.0.83")
    assert CE._valid_version("0.1.0-beta.1")
    assert not CE._valid_version("../../etc")
    assert not CE._valid_version("0.0.83/../../x")
    assert not CE._valid_version("")
    assert not CE._valid_version("0.0.83 nightly")


def test_install_flow_with_auto_default(tmp_path, monkeypatch):
    """安装流: 仓库构建(缺 dist 时触发)→ 拷贝 dist → npm 锁版 → 校验 → 元数据;
    首个安装自动设默认; resolve_engine 返回脚本+数据目录。"""
    _setup(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import cline_engines as CE
    root = tmp_path / "engines"
    src = tmp_path / "repo" / "packages" / "cline-sidecar"
    src.mkdir(parents=True)
    monkeypatch.setattr(CE, "engines_root", lambda: str(root))
    monkeypatch.setattr(CE, "sidecar_source_dir", lambda: str(src))
    monkeypatch.setattr(CE, "_node_version", lambda: "v22.1.0")

    calls = []

    def fake_run(cmd, **kw):
        calls.append(list(cmd))
        if "build" in cmd:
            dist = src / "dist"
            dist.mkdir(parents=True, exist_ok=True)
            (dist / "index.js").write_text("// built")
        else:
            # 模拟 npm install 产物: 锁版依赖落地
            sdk = pathlib.Path(kw.get("cwd") or ".") / "node_modules" / "@cline" / "sdk"
            sdk.mkdir(parents=True, exist_ok=True)
            (sdk / "package.json").write_text(json.dumps({"version": "0.0.83"}))
        return types.SimpleNamespace(returncode=0, stdout="added 1 package", stderr="")

    monkeypatch.setattr(CE, "subprocess", types.SimpleNamespace(run=fake_run))

    r = CE.install_engine("0.0.83")
    assert r["status"] == "ok", r["detail"]
    # 构建被触发(仓库无 dist) + npm 锁版安装
    assert any("build" in c for c in calls)
    assert any("@cline/sdk" not in c and "install" in c for c in calls)
    d = root / "0.0.83"
    assert (d / "dist" / "index.js").is_file()
    assert (d / "data").is_dir()
    pkg = json.loads((d / "package.json").read_text())
    assert pkg["dependencies"]["@cline/sdk"] == "0.0.83"    # 精确锁版无 ^
    assert json.loads((d / ".engine.json").read_text())["node"] == "v22.1.0"
    # 首个安装自动设默认 + 解析链
    assert CE.default_version() == "0.0.83"
    eng = CE.resolve_engine()
    assert eng and eng["version"] == "0.0.83"
    assert eng["script"].endswith("0.0.83/dist/index.js")
    assert eng["dataDir"].endswith("0.0.83/data")


def test_install_npm_failure_cleans_up(tmp_path, monkeypatch):
    """npm 失败(版本不存在/网络) → 引擎目录回滚清除。"""
    _setup(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import cline_engines as CE
    root = tmp_path / "engines"
    src = tmp_path / "repo" / "packages" / "cline-sidecar"
    (src / "dist").mkdir(parents=True)
    (src / "dist" / "index.js").write_text("//")
    monkeypatch.setattr(CE, "engines_root", lambda: str(root))
    monkeypatch.setattr(CE, "sidecar_source_dir", lambda: str(src))
    monkeypatch.setattr(CE, "subprocess", types.SimpleNamespace(run=lambda cmd, **kw:
        types.SimpleNamespace(returncode=1, stdout="", stderr="npm error 404 not found")))

    r = CE.install_engine("9.9.9")
    assert r["status"] == "fail"
    assert "404" in r["detail"]
    assert not (root / "9.9.9").exists()
    assert CE.default_version() == ""


def test_remove_guards_and_default_clear(tmp_path, monkeypatch):
    """移除守卫: 默认版本(多引擎时)拒移; 非默认可移; 唯一引擎可移(清默认回退内置)。"""
    _setup(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import cline_engines as CE
    root = tmp_path / "engines"
    monkeypatch.setattr(CE, "engines_root", lambda: str(root))
    _fake_engine(root, "0.0.82")
    _fake_engine(root, "0.0.83")
    assert CE.set_default_version("0.0.83") is None

    r = CE.remove_engine("0.0.83")          # 默认 + 多引擎 → 拒
    assert r["status"] == "fail" and "先切换默认" in r["detail"]
    assert CE.set_default_version("0.0.82") is None
    r = CE.remove_engine("0.0.83")          # 非默认 → 移
    assert r["status"] == "ok"
    assert not (root / "0.0.83").exists()
    r = CE.remove_engine("0.0.82")          # 唯一引擎(默认) → 移 + 清默认
    assert r["status"] == "ok"
    assert CE.default_version() == ""
    assert CE.resolve_engine() is None       # 回退仓库内置(解析返回 None)
    r = CE.remove_engine("0.0.82")          # 未安装 → fail
    assert r["status"] == "fail"


def test_set_default_validates_health(tmp_path, monkeypatch):
    """默认版本须已装且健康(缺依赖的损坏引擎拒设)。"""
    _setup(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import cline_engines as CE
    root = tmp_path / "engines"
    monkeypatch.setattr(CE, "engines_root", lambda: str(root))
    _fake_engine(root, "0.0.82", ok=False)   # 缺 node_modules
    assert CE.set_default_version("7.7.7")   # 未安装
    assert "未安装" in CE.set_default_version("7.7.7")
    msg = CE.set_default_version("0.0.82")   # 损坏
    assert msg and "损坏" in msg
    assert CE.default_version() == ""


def test_broken_engine_not_resolved(tmp_path, monkeypatch):
    """默认指向损坏引擎 → resolve_engine 返回 None(回退内置), 不带病下发。"""
    _setup(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import cline_engines as CE
    root = tmp_path / "engines"
    monkeypatch.setattr(CE, "engines_root", lambda: str(root))
    _fake_engine(root, "0.0.82")
    broken = _fake_engine(root, "0.0.83", ok=False)
    assert CE.set_default_version("0.0.83") and "损坏" in CE.set_default_version("0.0.83")
    # 直接写默认绕过校验(模拟外部破坏) → 解析拒
    from topoone_app_architect import store
    store.CollabConfigStore.set(CE.CONFIG_KEY, "0.0.83")
    assert CE.resolve_engine() is None
    assert CE.list_engines()[1]["ok"] is False and broken.endswith("0.0.83")


def test_available_versions_offline_and_cache(tmp_path, monkeypatch):
    """registry 断网 → error 降级不抛; 缓存生效; force 绕缓存。"""
    from topoone_app_architect.arch_routes import cline_engines as CE
    CE._avail_cache["ts"] = 0.0
    CE._avail_cache["data"] = None
    n = {"c": 0}

    def boom(req, timeout=0):
        n["c"] += 1
        raise OSError("network unreachable")

    monkeypatch.setattr(CE.urllib.request, "urlopen", boom)
    d1 = CE.available_versions()
    assert d1["versions"] == [] and "registry 不可达" in d1["error"]
    CE.available_versions()
    assert n["c"] == 1                       # 缓存命中不再请求
    d2 = CE.available_versions(force=True)
    assert n["c"] == 2


def test_exec_bridge_hint_injects_engine(tmp_path, monkeypatch):
    """任务下发解析链: 显式 sidecar_script 优先; 空时引擎默认版本注入
    (script + cline_data_dir); 无引擎回退仓库内置且不携带数据目录。"""
    _setup(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import agent_executors as AE
    from topoone_app_architect.agent.execution import exec_bridge as EB
    AE.save_executors([{"id": "cline", "type": "cline-sdk", "enabled": True,
                        "default": True,
                        "config": {"node_bin": "node", "sidecar_script": "",
                                   "provider_id": "p", "model_id": "m",
                                   "api_key": "", "max_iterations": 40,
                                   "capability": "", "system_prompt": "",
                                   "tool_policies": {}, "models": [],
                                   "mcp_servers": [],
                                   "teams": {"enabled": False, "teamName": "",
                                             "agents": []}}}])

    monkeypatch.setattr(AE, "_default_sidecar_path", lambda: "/repo/dist/index.js")
    # 无引擎 → 仓库内置, 不带 cline_data_dir
    hint = EB.executor_hint_by_id("cline")
    assert hint["executorConfig"]["sidecar_script"] == "/repo/dist/index.js"
    assert "cline_data_dir" not in hint["executorConfig"]
    # 引擎默认版本 → 注入脚本 + 数据目录
    monkeypatch.setattr("topoone_app_architect.arch_routes.cline_engines.resolve_engine",
                        lambda: {"version": "0.0.83",
                                 "script": "/eng/0.0.83/dist/index.js",
                                 "dataDir": "/eng/0.0.83/data"})
    hint = EB.executor_hint_by_id("cline")
    assert hint["executorConfig"]["sidecar_script"] == "/eng/0.0.83/dist/index.js"
    assert hint["executorConfig"]["cline_data_dir"] == "/eng/0.0.83/data"
    # 显式 sidecar_script 优先于引擎
    entries = AE.load_executors()
    entries[0]["config"]["sidecar_script"] = "/custom/sidecar.js"
    AE.save_executors(entries)
    hint = EB.executor_hint_by_id("cline")
    assert hint["executorConfig"]["sidecar_script"] == "/custom/sidecar.js"
    assert "cline_data_dir" not in hint["executorConfig"]


def test_env_detect_reports_engines(tmp_path, monkeypatch):
    """环境检测携带引擎清单与默认版本(前端概览面)。"""
    _setup(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import agent_executors as AE
    from topoone_app_architect.arch_routes import cline_engines as CE
    root = tmp_path / "engines"
    monkeypatch.setattr(CE, "engines_root", lambda: str(root))
    _fake_engine(root, "0.0.82")
    assert CE.set_default_version("0.0.82") is None
    monkeypatch.setattr(AE, "_default_sidecar_path",
                        lambda: str(tmp_path / "nonexistent" / "index.js"))
    env = AE._env_detect()["cline"]
    assert env["engines"] == ["0.0.82"]
    assert env["engineDefault"] == "0.0.82"
