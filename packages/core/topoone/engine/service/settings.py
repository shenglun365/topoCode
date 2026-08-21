"""settings.* 设置命名空间 —— 原 core_service.py 解构（M03 T3.2）。"""
import logging

import asyncio
import time
import json
import os
import uuid
from datetime import datetime
from topoone.db.manager import SQLiteContext, MultiDBManager
from topoone.rpc.zmq_server import ZMQServer

logger = logging.getLogger(__name__)

from topoone.engine.service._common import _load_import_config
def register_settings_methods(server: ZMQServer, multi_db: MultiDBManager):
    """注册设置配置方法"""
    main_db = multi_db.main_db

    @server.register("settings.getModels")
    def get_models():
        rows = main_db.fetchall("SELECT * FROM model_configs ORDER BY is_default DESC, name")
        for row in rows:
            row["isDefault"] = bool(row.get("is_default"))
            # 安全：不返回 api_key，只标记是否存在
            row["hasApiKey"] = bool(row.get("api_key"))
            if row.get("api_key"):
                del row["api_key"]
            if row.get("extra_config"):
                try:
                    row["extraConfig"] = json.loads(row["extra_config"])
                except (json.JSONDecodeError, TypeError):
                    row["extraConfig"] = {}
        return rows

    @server.register("settings.addModel")
    def add_model(name: str, provider: str, model: str, url: str, type: str = "local", **kwargs):
        now = datetime.now().isoformat()

        # 去重: 同名 + 同 provider 的模型自动更新
        existing = main_db.fetchone(
            "SELECT id FROM model_configs WHERE name = ? AND provider = ?",
            (name, provider),
        )
        if existing:
            logger.info(f"[addModel] model already exists, auto-updating: {existing['id']} ({name}/{provider})")
            return update_model(existing["id"], **kwargs,
                              name=name, provider=provider, model=model, url=url, type=type)

        model_id = f"model-{uuid.uuid4().hex[:8]}"

        if kwargs.get("isDefault"):
            main_db.execute("UPDATE model_configs SET is_default = 0")

        # 统一 URL 格式：去掉末尾的 /v1（兼容用户输入 https://xxx/v1 的情况）
        clean_url = url.rstrip('/')
        if clean_url.endswith('/v1'):
            clean_url = clean_url[:-3]

        data = {
            "id": model_id,
            "name": name,
            "provider": provider,
            "model": model,
            "url": clean_url,
            "type": type,
            "status": "offline",
            "is_default": 1 if kwargs.get("isDefault") else 0,
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("maxTokens", 16384),
            "frequency_penalty": kwargs.get("frequencyPenalty", 0.0),
            "presence_penalty": kwargs.get("presencePenalty", 0.0),
            "timeout": kwargs.get("timeout", 300),
            "extra_config": json.dumps(kwargs["extraConfig"]) if kwargs.get("extraConfig") else None,
            "context_window": kwargs.get("contextWindow", 8192),
            "created_at": now,
            "updated_at": now,
        }
        if kwargs.get("apiKey"):
            data["api_key"] = kwargs["apiKey"]

        main_db.insert("model_configs", data)
        row = main_db.fetchone("SELECT * FROM model_configs WHERE id = ?", (model_id,))
        if row and row.get("extra_config"):
            try:
                row["extraConfig"] = json.loads(row["extra_config"])
            except (json.JSONDecodeError, TypeError):
                row["extraConfig"] = {}
        return row

    @server.register("settings.updateModel")
    def update_model(id: str, **kwargs):
        allowed = {"name", "temperature", "maxTokens", "url", "isDefault", "provider", "model", "apiKey", "maxRequestsPerDay", "maxTokensPerDay", "frequencyPenalty", "presencePenalty", "timeout", "contextWindow", "extraConfig"}
        data = {}
        for k, v in kwargs.items():
            if k == "isDefault":
                if v:
                    main_db.execute("UPDATE model_configs SET is_default = 0")
                data["is_default"] = 1 if v else 0
            elif k == "maxTokens":
                data["max_tokens"] = v
            elif k == "frequencyPenalty":
                data["frequency_penalty"] = v
            elif k == "presencePenalty":
                data["presence_penalty"] = v
            elif k == "maxRequestsPerDay":
                data["max_requests_per_day"] = int(v) if v else 0
            elif k == "maxTokensPerDay":
                data["max_tokens_per_day"] = int(v) if v else 0
            elif k == "apiKey":
                if v:
                    data["api_key"] = v
            elif k == "timeout":
                data["timeout"] = int(v) if v else 300
            elif k == "contextWindow":
                data["context_window"] = int(v) if v else 8192
            elif k == "extraConfig":
                data["extra_config"] = json.dumps(v) if isinstance(v, dict) else str(v)
            elif k == "url":
                clean_url = v.rstrip('/')
                if clean_url.endswith('/v1'):
                    clean_url = clean_url[:-3]
                data["url"] = clean_url
            elif k in allowed:
                data[k] = v
        data["updated_at"] = datetime.now().isoformat()

        main_db.update("model_configs", data, "id = ?", (id,))
        row = main_db.fetchone("SELECT * FROM model_configs WHERE id = ?", (id,))
        if row and row.get("extra_config"):
            try:
                row["extraConfig"] = json.loads(row["extra_config"])
            except (json.JSONDecodeError, TypeError):
                row["extraConfig"] = {}
        return row

    @server.register("settings.removeModel")
    def remove_model(id: str):
        main_db.delete("model_configs", "id = ?", (id,))

    @server.register("settings.testModel")
    async def test_model(id: str):
        """测试模型连接 — 自适应 API Key，如实返回服务端错误"""
        model = main_db.fetchone("SELECT * FROM model_configs WHERE id = ?", (id,))
        if not model:
            raise ValueError(f"Model not found: {id}")

        import requests as req
        start = __import__('time').time()
        try:
            base = model['url'].rstrip('/')
            if base.endswith('/v1'):
                base = base[:-3]
            headers = {'Content-Type': 'application/json'}
            api_key = model.get('api_key')
            if api_key:
                headers['Authorization'] = f"Bearer {api_key}"

            if model.get('provider') == 'ollama':
                resp = req.post(f"{base}/api/tags", timeout=10)
            else:
                payload = {
                    "model": model["model"],
                    "messages": [{"role": "user", "content": "test"}],
                    "max_tokens": 1,
                    "stream": False,
                }
                resp = req.post(f"{base}/v1/chat/completions",
                                json=payload, headers=headers, timeout=15)

            latency = int((__import__('time').time() - start) * 1000)

            if resp.status_code == 200:
                try:
                    main_db.update("model_configs", {"status": "connected"}, "id = ?", (id,))
                except Exception:
                    pass
                return {"status": "connected", "latency": latency, "model": model["model"]}
            else:
                msg = f"HTTP {resp.status_code}"
                try:
                    body = resp.json()
                    if "error" in body:
                        msg = str(body["error"])
                    elif "message" in body:
                        msg = str(body["message"])
                except Exception:
                    msg = resp.text[:200] if resp.text else msg
                return {"status": "error", "latency": latency, "error": msg}

        except Exception as e:
            return {"status": "error", "latency": 0, "error": str(e)}

    @server.register("settings.getAgents")
    def get_agents():
        rows = main_db.fetchall("SELECT * FROM agent_configs ORDER BY is_default DESC, name")
        for row in rows:
            row["isDefault"] = bool(row.get("is_default"))
        return rows

    @server.register("settings.addAgent")
    def add_agent(name: str, path: str, args: str = "", type: str = "custom"):
        agent_id = f"agent-{uuid.uuid4().hex[:8]}"
        now = datetime.now().isoformat()

        main_db.insert("agent_configs", {
            "id": agent_id,
            "name": name,
            "type": type,
            "path": path,
            "args": args,
            "status": "configured",
            "created_at": now,
            "updated_at": now,
        })

        return main_db.fetchone("SELECT * FROM agent_configs WHERE id = ?", (agent_id,))

    @server.register("settings.updateAgent")
    def update_agent(id: str, **kwargs):
        allowed = {"path", "args", "name", "type"}
        data = {k: v for k, v in kwargs.items() if k in allowed}
        data["updated_at"] = datetime.now().isoformat()

        main_db.update("agent_configs", data, "id = ?", (id,))
        return main_db.fetchone("SELECT * FROM agent_configs WHERE id = ?", (id,))

    @server.register("settings.removeAgent")
    def remove_agent(id: str):
        main_db.delete("agent_configs", "id = ?", (id,))

    @server.register("settings.detectAgent")
    async def detect_agent(id: str):
        agent = main_db.fetchone("SELECT * FROM agent_configs WHERE id = ?", (id,))
        if not agent:
            raise ValueError(f"Agent not found: {id}")

        if os.path.exists(agent["path"]):
            status = "online"
            version = "unknown"
            try:
                result = os.popen(f'{agent["path"]} --version 2>/dev/null').read().strip()
                if result:
                    version = result
            except:
                pass
        else:
            status = "not-detected"
            version = None

        main_db.update("agent_configs", {"status": status, "version": version}, "id = ?", (id,))

        return {"status": status, "version": version}

    @server.register("settings.executeAgent")
    async def execute_agent(id: str, task: str = "", args: str = "", task_id: str = "", env: dict = None):
        """异步执行外部 Agent 命令，写入 agent_executions 表追踪状态"""
        import shlex
        import tempfile

        agent = main_db.fetchone("SELECT * FROM agent_configs WHERE id = ?", (id,))
        if not agent:
            raise ValueError(f"Agent not found: {id}")

        exec_id = f"aex-{uuid.uuid4().hex[:8]}"
        user_args = shlex.split(args or "") if args else []
        cmd_parts = [agent["path"]] + shlex.split(agent["args"] or "") + user_args
        if task:
            cmd_parts.append(task)
        cmd = " ".join(cmd_parts)

        stdout_fd, stdout_path = tempfile.mkstemp(prefix=f"agent-exec-{exec_id}-stdout-", suffix=".log")
        stderr_fd, stderr_path = tempfile.mkstemp(prefix=f"agent-exec-{exec_id}-stderr-", suffix=".log")
        os.close(stdout_fd)
        os.close(stderr_fd)

        proc_env = os.environ.copy()
        if agent["env"]:
            try:
                proc_env.update(json.loads(agent["env"]))
            except Exception:
                pass
        if env:
            proc_env.update(env)

        now = datetime.now().isoformat()
        main_db.insert("agent_executions", {
            "id": exec_id,
            "agent_config_id": id,
            "task_id": task_id or "",
            "status": "queued",
            "args": args,
            "env": json.dumps(env) if env else "",
            "command": cmd,
            "stdout_path": stdout_path,
            "stderr_path": stderr_path,
            "created_at": now,
        })

        async def _run():
            started = datetime.now().isoformat()
            main_db.update("agent_executions", {"status": "running", "started_at": started}, "id = ?", (exec_id,))
            try:
                proc = await asyncio.create_subprocess_shell(
                    cmd, stdout=open(stdout_path, "w"), stderr=open(stderr_path, "w"),
                    env=proc_env,
                )
                timeout = agent.get("timeout", 300) / 1000.0 if agent.get("timeout") else 300.0
                try:
                    exit_code = await asyncio.wait_for(proc.wait(), timeout=timeout)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
                    exit_code = -1
                    error = f"timeout after {timeout}s"

                finished = datetime.now().isoformat()
                started_ts = datetime.fromisoformat(started)
                finished_ts = datetime.fromisoformat(finished)
                duration = int((finished_ts - started_ts).total_seconds() * 1000)

                final_status = "completed" if exit_code == 0 else ("timed_out" if exit_code == -1 else "failed")
                main_db.update("agent_executions", {
                    "status": final_status,
                    "exit_code": exit_code,
                    "finished_at": finished,
                    "duration_ms": duration,
                    "error": error or "",
                }, "id = ?", (exec_id,))
            except Exception as e:
                logger.exception(f"executeAgent {exec_id} crashed")
                main_db.update("agent_executions", {
                    "status": "failed", "error": str(e),
                    "finished_at": datetime.now().isoformat(),
                }, "id = ?", (exec_id,))

        asyncio.get_event_loop().create_task(_run())
        return {"id": exec_id, "agentId": id, "command": cmd, "status": "queued"}

    @server.register("settings.getAgentExecution")
    def get_agent_execution(exec_id: str):
        row = main_db.fetchone("SELECT * FROM agent_executions WHERE id = ?", (exec_id,))
        if not row:
            return {"found": False}
        return row

    @server.register("settings.listAgentExecutions")
    def list_agent_executions(agent_id: str = "", task_id: str = "", status_filter: str = "", limit: int = 50):
        where = ["1=1"]
        params = []
        if agent_id:
            where.append("agent_config_id = ?")
            params.append(agent_id)
        if task_id:
            where.append("task_id = ?")
            params.append(task_id)
        if status_filter:
            statuses = [s.strip() for s in status_filter.split(",") if s.strip()]
            if statuses:
                where.append("status IN (" + ",".join("?" for _ in statuses) + ")")
                params.extend(statuses)
        sql = f"SELECT * FROM agent_executions WHERE {' AND '.join(where)} ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        return main_db.fetchall(sql, tuple(params))

    @server.register("settings.cancelAgentExecution")
    def cancel_agent_execution(exec_id: str):
        row = main_db.fetchone("SELECT * FROM agent_executions WHERE id = ?", (exec_id,))
        if not row:
            raise ValueError(f"Agent execution not found: {exec_id}")
        if row["status"] not in ("queued", "running"):
            return {"cancelled": False, "message": f"status is {row['status']}"}
        main_db.update("agent_executions", {"status": "cancelled", "finished_at": datetime.now().isoformat()}, "id = ?", (exec_id,))
        return {"cancelled": True}

    @server.register("settings.getSkills")
    def get_skills():
        rows = main_db.fetchall("SELECT * FROM skill_configs ORDER BY name")
        for row in rows:
            row["enabled"] = bool(row.get("enabled"))
            if row.get("config"):
                row["config"] = json.loads(row["config"])
        return rows

    @server.register("settings.updateSkill")
    def update_skill(id: str, enabled: bool):
        main_db.update("skill_configs", {"enabled": 1 if enabled else 0, "updated_at": datetime.now().isoformat()}, "id = ?", (id,))
        return main_db.fetchone("SELECT * FROM skill_configs WHERE id = ?", (id,))

    @server.register("settings.getBindings")
    def get_bindings():
        rows = main_db.fetchall("SELECT task_type, model_id FROM task_model_bindings")
        return {row["task_type"]: row["model_id"] for row in rows}

    @server.register("settings.updateBindings")
    def update_bindings(bindings: dict):
        for task_type, model_id in bindings.items():
            main_db.execute(
                "INSERT OR REPLACE INTO task_model_bindings (id, task_type, model_id) VALUES (?, ?, ?)",
                (f"bind-{task_type}", task_type, model_id),
            )
        return bindings

    # ==================== 模型用量统计 ====================

    # 确保 model_daily_usage 表存在（兼容旧版本升级）
    def _ensure_usage_table():
        try:
            main_db.execute("SELECT 1 FROM model_daily_usage LIMIT 1")
        except Exception:
            main_db.execute("""CREATE TABLE IF NOT EXISTS model_daily_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                model_id TEXT NOT NULL REFERENCES model_configs(id) ON DELETE CASCADE,
                date TEXT NOT NULL,
                request_count INTEGER DEFAULT 0,
                prompt_tokens INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                UNIQUE(model_id, date)
            )""")
        # 确保索引存在（每次调用都执行，兼容旧版本升级）
        for idx_sql in [
            "CREATE INDEX IF NOT EXISTS idx_mdu_model ON model_daily_usage(model_id)",
            "CREATE INDEX IF NOT EXISTS idx_mdu_date ON model_daily_usage(date)",
            "CREATE INDEX IF NOT EXISTS idx_mdu_model_date ON model_daily_usage(model_id, date)",
        ]:
            try:
                main_db.execute(idx_sql)
            except Exception:
                pass

    @server.register("model.getUsageStats")
    def get_usage_stats(model_id: str = None, start_date: str = None, end_date: str = None):
        _ensure_usage_table()
        sql = "SELECT d.*, m.name AS model_name FROM model_daily_usage d JOIN model_configs m ON d.model_id = m.id WHERE 1=1"
        params = []
        if model_id:
            sql += " AND d.model_id = ?"
            params.append(model_id)
        if start_date:
            sql += " AND d.date >= ?"
            params.append(start_date)
        if end_date:
            sql += " AND d.date <= ?"
            params.append(end_date)
        sql += " ORDER BY d.date DESC, m.name"
        rows = main_db.fetchall(sql, tuple(params))
        for row in rows:
            row["modelId"] = row.pop("model_id")
            row["requestCount"] = row.pop("request_count")
            row["promptTokens"] = row.pop("prompt_tokens")
            row["completionTokens"] = row.pop("completion_tokens")
            row["totalTokens"] = row.pop("total_tokens")
            row["modelName"] = row.pop("model_name")
        return rows

    @server.register("model.deleteUsageStats")
    def delete_usage_stats(id: int):
        _ensure_usage_table()
        main_db.delete("model_daily_usage", "id = ?", (id,))

    @server.register("model.deleteUsageStatsBatch")
    def delete_usage_stats_batch(ids: list):
        _ensure_usage_table()
        if not ids:
            return
        placeholders = ",".join("?" * len(ids))
        main_db.execute(f"DELETE FROM model_daily_usage WHERE id IN ({placeholders})", tuple(ids))

    @server.register("model.deleteUsageStatsByCondition")
    def delete_usage_stats_by_condition(model_id: str = None, start_date: str = None, end_date: str = None):
        _ensure_usage_table()
        sql = "DELETE FROM model_daily_usage WHERE 1=1"
        params = []
        if model_id:
            sql += " AND model_id = ?"
            params.append(model_id)
        if start_date:
            sql += " AND date >= ?"
            params.append(start_date)
        if end_date:
            sql += " AND date <= ?"
            params.append(end_date)
        main_db.execute(sql, tuple(params))

    # ==================== 导入配置 ====================

    @server.register("settings.getImportConfig")
    def get_import_config():
        """获取导入配置（忽略模式、自定义模式、额外 ignore 文件）"""
        return _load_import_config(main_db)

    @server.register("settings.setImportConfig")
    def set_import_config(ignore_mode: str = None, custom_patterns: list = None, extra_ignore_files: list = None):
        """保存导入配置"""
        now = datetime.now().isoformat()
        if ignore_mode is not None:
            main_db.execute(
                "INSERT OR REPLACE INTO app_config (key, value, updated_at) VALUES (?, ?, ?)",
                ("import_ignore_mode", ignore_mode, now),
            )
        if custom_patterns is not None:
            main_db.execute(
                "INSERT OR REPLACE INTO app_config (key, value, updated_at) VALUES (?, ?, ?)",
                ("import_custom_patterns", json.dumps(custom_patterns), now),
            )
        if extra_ignore_files is not None:
            main_db.execute(
                "INSERT OR REPLACE INTO app_config (key, value, updated_at) VALUES (?, ?, ?)",
                ("import_extra_ignore_files", json.dumps(extra_ignore_files), now),
            )
        return _load_import_config(main_db)

    return server


# ==================== 后端管理方法 ====================
