"""owner_app 域隔离: 子应用(architect)注册的模型不进 KB 模型列表, 推理按 id 不受影响。

- getModels 只返回 KB 自有条目(COALESCE(owner_app,'')='')
- addModel(ownerApp=...) 注册专属域; 同名同 provider 幂等(update 不新建)
- 域隔离: KB 自有条目不被 architect 注册覆盖, 双 id 并存
- 旧库无 owner_app 列 → 注册时惰性 ALTER 兼容
"""

import sqlite3


MODEL_CONFIGS_BASE = """
CREATE TABLE model_configs (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    provider TEXT NOT NULL CHECK(provider IN ('ollama', 'lm-studio', 'custom-local', 'deepseek', 'minimax-cn', 'minimax-global', 'openrouter', 'custom-cloud')),
    model TEXT NOT NULL,
    url TEXT NOT NULL,
    api_key TEXT DEFAULT '',
    type TEXT DEFAULT 'local' CHECK(type IN ('local', 'cloud')),
    status TEXT DEFAULT 'offline' CHECK(status IN ('offline', 'connected', 'error')),
    is_default INTEGER DEFAULT 0,
    temperature REAL DEFAULT 0.7,
    max_tokens INTEGER DEFAULT 16384,
    frequency_penalty REAL DEFAULT 0.0,
    presence_penalty REAL DEFAULT 0.0,
    timeout INTEGER DEFAULT 300,
    context_window INTEGER DEFAULT 8192,
    extra_config TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
)
"""


class _FakeDB:
    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=()):
        return self._conn.execute(sql, params)

    def fetchone(self, sql, params=()):
        row = self._conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    def fetchall(self, sql, params=()):
        return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def insert(self, table, data):
        cols = ",".join(data)
        ph = ",".join("?" for _ in data)
        self._conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({ph})", tuple(data.values()))

    def update(self, table, data, where, params):
        sets = ",".join(f"{k}=?" for k in data)
        self._conn.execute(f"UPDATE {table} SET {sets} WHERE {where}", tuple(data.values()) + tuple(params))


class _FakeServer:
    def __init__(self):
        self.methods = {}

    def register(self, name):
        def deco(fn):
            self.methods[name] = fn
            return fn
        return deco


def _make_server(with_owner_col=True):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    schema = MODEL_CONFIGS_BASE
    if with_owner_col:
        schema = schema.replace(
            "updated_at TEXT DEFAULT (datetime('now'))\n)",
            "updated_at TEXT DEFAULT (datetime('now')),\n    owner_app TEXT DEFAULT '')")
    conn.execute(schema)
    from topoone.engine.service.settings import register_settings_methods
    server = _FakeServer()
    register_settings_methods(server, type("M", (), {"main_db": _FakeDB(conn)}))
    return server.methods, _FakeDB(conn)


def test_owner_domain_isolation():
    api, db = _make_server()
    # KB 自有条目
    kb_row = api["settings.addModel"](name="LMS-9b", provider="lm-studio",
                                      model="qwen3.5-9b-mtp", url="http://10.0.0.75:1234")
    # architect 注册(同名 model 不同 name → 独立条目; 同 name 场景见下一个用例)
    arch_row = api["settings.addModel"](name="LMS-4b", provider="lm-studio",
                                        model="qwen3.5-4b-mtp", url="http://10.0.0.75:1234",
                                        ownerApp="architect")
    visible = [r["id"] for r in api["settings.getModels"]()]
    assert kb_row["id"] in visible, "KB 自有条目应可见"
    assert arch_row["id"] not in visible, "architect 注册不应进 KB 模型列表"
    assert db.fetchone("SELECT * FROM model_configs WHERE id=?", (arch_row["id"],))["owner_app"] == "architect"


def test_owner_domain_dedup_and_no_cross_cover():
    api, db = _make_server()
    # KB 自有同名条目
    kb1 = api["settings.addModel"](name="LMS-4b", provider="lm-studio",
                                   model="qwen3.5-4b-mtp", url="http://a")
    # architect 同 name+provider 注册 → 各自域独立, 不覆盖 KB 条目
    arch1 = api["settings.addModel"](name="LMS-4b", provider="lm-studio",
                                     model="qwen3.5-4b-mtp", url="http://a",
                                     ownerApp="architect")
    assert arch1["id"] != kb1["id"], "跨 owner 域不应互相覆盖"
    assert db.fetchone("SELECT COUNT(*) c FROM model_configs")["c"] == 2
    # architect 域内幂等: 再注册同 name+provider → 复用 id(update 而非新建)
    arch2 = api["settings.addModel"](name="LMS-4b", provider="lm-studio",
                                     model="qwen3.5-4b-mtp", url="http://a",
                                     ownerApp="architect")
    assert arch2["id"] == arch1["id"], "同域同名应幂等复用"
    assert db.fetchone("SELECT COUNT(*) c FROM model_configs")["c"] == 2
    # KB 列表只见自有 1 条
    assert len(api["settings.getModels"]()) == 1


def test_legacy_table_without_owner_column():
    """旧库无 owner_app 列 → 注册时惰性 ALTER, 功能不回归。"""
    api, db = _make_server(with_owner_col=False)
    row = api["settings.addModel"](name="n", provider="lm-studio", model="m", url="http://u")
    assert row["id"].startswith("model-")
    assert len(api["settings.getModels"]()) == 1
