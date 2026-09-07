#!/usr/bin/env python3
"""TopoCode 执行通道一键配置（本地模型版）。

职责：
  1. 生成各 codex 实例的 CODEX_HOME（config.toml 指向本地 llama.cpp，实例间隔离）
  2. 写入 architect 执行器注册表（opencode / cline 自主模式 / codex-27b / codex-35b）
  3. 触发 runner 热刷新
  4. 探活：本地端点 /v1/models、runner 执行器健康、codex 配置解析（model/list）

用法：
  python3 scripts/configure_agents.py            # 写配置 + 刷新 + 探活
  python3 scripts/configure_agents.py --check    # 只探活不写
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

ARCH = os.environ.get("ARCH_BASE_URL", "http://127.0.0.1:3470")
RUNNER = os.environ.get("RUNNER_BASE_URL", "http://127.0.0.1:3458")
DATA_DIR = os.environ.get("TOPOCODE_DATA_DIR", os.path.expanduser("~/.topocode"))

# ── 用户决策（2026-09 配置）────────────────────────────────
LLAMA_27B = "http://192.168.1.76:8200/v1"     # Qwen3.8-27B（cline 自主模式 + codex-27b）
LLAMA_35B = "http://192.168.1.76:8201/v1"     # Qwen3.6-35B-A3B（codex-35b）
LMSTUDIO = "http://192.168.1.9:1234/v1"       # qwen3.5-9b-mtp（未分配执行器，预留）
MODEL_27B = "Qwen3.8-27B"
MODEL_35B = "Qwen3.6-35B-A3B"
DEFAULT_EXECUTOR = "cline"
CTX_WINDOW = 262144                            # 256K
# ──────────────────────────────────────────────────────────


def _post(url: str, payload: dict, timeout: float = 15.0, method: str = "POST"):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"},
                                 method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _get(url: str, timeout: float = 8.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())


def codex_config_toml(model: str, base_url: str, name: str) -> str:
    """codex 0.147 本地 provider 配置（无需登录）。"""
    return (
        f'model = "{model}"\n'
        f'model_provider = "local"\n'
        f"model_context_window = {CTX_WINDOW}\n"
        "\n"
        "[model_providers.local]\n"
        f'name = "{name}"\n'
        f'base_url = "{base_url}"\n'
        'wire_api = "chat"\n'
    )


def setup_codex_home(home: str, model: str, base_url: str, name: str) -> str:
    os.makedirs(home, exist_ok=True)
    cfg = os.path.join(home, "config.toml")
    bak = cfg + ".bak"
    if os.path.exists(cfg) and not os.path.exists(bak):
        shutil.copy2(cfg, bak)
    with open(cfg, "w") as f:
        f.write(codex_config_toml(model, base_url, name))
    return cfg


def registry_entries() -> list[dict]:
    return [
        {"id": "opencode", "type": "opencode", "enabled": True,
         "default": DEFAULT_EXECUTOR == "opencode",
         "config": {"auto_start": True, "base_port": 3478, "permission": "auto",
                    "timeout": 1800, "model": ""}},
        {"id": "cline", "type": "cline-sdk", "enabled": True,
         "default": DEFAULT_EXECUTOR == "cline",
         "config": {"node_bin": "node", "sidecar_script": "",
                    "provider_id": "openai-compatible", "model_id": MODEL_27B,
                    "base_url": LLAMA_27B, "api_key": "", "max_iterations": 40}},
        {"id": "codex-27b", "type": "codex-server", "enabled": True,
         "default": DEFAULT_EXECUTOR == "codex-27b",
         "config": {"codex_bin": "codex", "model": MODEL_27B,
                    "codex_home": os.path.join(DATA_DIR, "codex-home-27b"),
                    "approval_policy": "never", "sandbox_mode": "workspace-write",
                    "timeout": 3600}},
        {"id": "codex-35b", "type": "codex-server", "enabled": True,
         "default": DEFAULT_EXECUTOR == "codex-35b",
         "config": {"codex_bin": "codex", "model": MODEL_35B,
                    "codex_home": os.path.join(DATA_DIR, "codex-home-35b"),
                    "approval_policy": "never", "sandbox_mode": "workspace-write",
                    "timeout": 3600}},
    ]


def probe_endpoint(name: str, base: str) -> bool:
    try:
        with urllib.request.urlopen(f"{base.rstrip('/')}/models", timeout=6) as r:
            data = json.loads(r.read().decode())
            ids = [m.get("id") for m in (data.get("data") or [])][:6]
            print(f"  ✓ {name}: {base}/models → {ids}")
            return True
    except Exception as e:  # noqa: BLE001
        print(f"  ✗ {name}: {base} → {e}")
        return False


def probe_codex_config(home: str, label: str) -> bool:
    """spawn app-server 验证 config.toml 解析 + model/list。"""
    env = dict(os.environ, CODEX_HOME=home)
    try:
        p = subprocess.Popen(["codex", "app-server"], env=env,
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, text=True, bufsize=1)
    except FileNotFoundError:
        print(f"  ✗ {label}: codex 未安装")
        return False
    out = []

    def reader():
        for line in p.stdout:
            out.append(line.strip())

    import threading
    threading.Thread(target=reader, daemon=True).start()

    def send(o):
        p.stdin.write(json.dumps(o) + "\n")
        p.stdin.flush()

    send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
          "params": {"clientInfo": {"name": "topoone-config", "version": "0"}}})
    time.sleep(2)
    send({"jsonrpc": "2.0", "id": 2, "method": "model/list", "params": {}})
    time.sleep(2)
    p.kill()
    for line in out:
        try:
            m = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        if m.get("id") == 2 and "result" in m:
            models = [x.get("modelId") or x.get("id") for x in (m["result"].get("models") or [])][:5]
            print(f"  ✓ {label}: codex 配置解析 OK，模型目录: {models}")
            return True
        if m.get("id") == 2 and "error" in m:
            print(f"  ✗ {label}: {str(m['error'])[:160]}")
            return False
    print(f"  ✗ {label}: app-server 无响应")
    return False


def main() -> int:
    apply = "--check" not in sys.argv
    rc = 0

    print("═　本地端点探活")
    ok27 = probe_endpoint("llama.cpp 27B", LLAMA_27B)
    ok35 = probe_endpoint("llama.cpp 35B", LLAMA_35B)
    rc |= 0 if (ok27 and ok35) else 1
    if not apply:
        return rc

    print("═　生成 CODEX_HOME（实例隔离，不影响 ~/.codex）")
    c1 = setup_codex_home(os.path.join(DATA_DIR, "codex-home-27b"),
                          MODEL_27B, LLAMA_27B, "llama.cpp Qwen3.8-27B")
    c2 = setup_codex_home(os.path.join(DATA_DIR, "codex-home-35b"),
                          MODEL_35B, LLAMA_35B, "llama.cpp Qwen3.6-35B-A3B")
    print(f"  ✓ {c1}")
    print(f"  ✓ {c2}")

    print("═　写入执行器注册表 → architect")
    entries = registry_entries()
    r = _post(f"{ARCH}/api/architect/agent/executors", {"executors": entries},
              method="PUT")
    d = r.get("data") or {}
    print(f"  ✓ saved={d.get('saved')} runnerRefreshed={d.get('runnerRefreshed')}")

    print("═　runner 热刷新确认（等待池替换生效）")
    want = {e["id"] for e in entries if e.get("enabled", True)}
    pool = []
    for _ in range(10):
        time.sleep(1.0)
        rt = _get(f"{RUNNER}/api/executors")
        pool = rt.get("executors") or []
        if want.issubset(set(pool)):
            break
    ok = want.issubset(set(pool))
    mark = "✓" if ok else "✗（architect 瞬时不稳会回退内置池，稍后重跑 --check 或手动刷新）"
    print(f"  {mark} executors: {pool}")

    print("═　codex 配置解析验证")
    probe_codex_config(os.path.join(DATA_DIR, "codex-home-27b"), "codex-27b")
    probe_codex_config(os.path.join(DATA_DIR, "codex-home-35b"), "codex-35b")

    print("═　完成。执行器：")
    for e in entries:
        star = "（默认）" if e.get("default") else ""
        print(f"  - {e['id']} [{e['type']}] {star}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
