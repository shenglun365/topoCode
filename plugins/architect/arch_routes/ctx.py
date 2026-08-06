"""Architect 运行时上下文(注入层) — architect 独立于宿主进程。

architect 不再依赖 reports `common.multi_db` / `common.zmq_server` 全局：
- 自己的 architect.db(SQLiteContext，独立连接)经 `db()` 访问；
- 与 KB 的一切接触经 `KbGateway`(`kb()`) 走 HTTP API(/zmq) 与 MCP(/v1/tools)。

独立进程启动时调用 `setup(data_dir)`；嵌入式/测试可只调用 `setup()` 得到默认库。
`store._db()`/`project._kb_call` 均只消费本模块，不再触碰 reports 包。
"""
import os

_db = None          # SQLiteContext (architect.db)
_kb = None          # KbGateway


def default_data_dir() -> str:
    return os.environ.get("ARCH_DATA_DIR") or os.path.join(os.path.expanduser("~"), ".topocode")


def setup(data_dir: str = None, kb_url: str = None, mcp_url: str = None):
    """初始化上下文。data_dir 缺省取 ARCH_DATA_DIR / ~/.topocode。"""
    global _db, _kb
    from .kb_gateway import KbGateway
    data_dir = data_dir or default_data_dir()
    os.makedirs(data_dir, exist_ok=True)
    if _kb is None:
        _kb = KbGateway(base_url=kb_url, mcp_url=mcp_url)
    if _db is None:
        from sqlite_ctx import SQLiteContext, init_architect_db
        db_path = os.path.join(data_dir, "architect.db")
        _db = SQLiteContext(db_path, label="architect")
        init_architect_db(_db)
    return _db


def db():
    return _db


def default_db():
    """嵌入式/测试用的默认库(懒建，落在默认数据目录)。"""
    if _db is None:
        setup()
    return _db


def kb():
    return _kb
