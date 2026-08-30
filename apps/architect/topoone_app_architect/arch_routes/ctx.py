"""Architect 运行时上下文(注入层) — architect 独立于宿主进程。

architect 不再依赖 reports `common.multi_db` / `common.zmq_server` 全局：
- 主库 architect.db(SQLiteContext，独立连接)经 `db()` 访问(全局表 + 项目注册表，
  兼「未绑定项目」默认桶)；
- 每 architect 项目独立库 `architect/<project_id>/arch.db` 经 `project_db(pid)`
  访问(LRU 缓存)，请求级项目定位经 `set_project/get_project` contextvar；
- 与 KB 的一切接触经 `KbGateway`(`kb()`) 走 HTTP API(/zmq) 与 MCP(/v1/tools)。
- 建表/迁移由本包 `db_schema` 自持(见 db_schema.py)；
  `SQLiteContext` 连接类与 KB 共享依赖库(`sqlite_ctx`)但不读写 KB 库文件。

独立进程启动时调用 `setup(data_dir)`；嵌入式/测试可只调用 `setup()` 得到默认库。
`store`/路由均只消费本模块，不再触碰 KB 包。
"""
import contextvars
import glob
import os
import threading

_db = None          # SQLiteContext (architect.db 主库)
_kb = None          # KbGateway
_data_dir = None    # setup 注入的数据目录

# 请求级项目定位(HTTP 中间件/WS 首消息设置；后台线程需显式传入)
_project_var: contextvars.ContextVar = contextvars.ContextVar(
    "architect_project_id", default=None)

_project_dbs: dict = {}   # pid -> SQLiteContext (architect/<pid>/arch.db)
_project_lock = threading.Lock()


def default_data_dir() -> str:
    return os.environ.get("ARCH_DATA_DIR") or os.path.join(os.path.expanduser("~"), ".topocode")


def data_dir() -> str:
    return _data_dir or default_data_dir()


def setup(data_dir: str = None, kb_url: str = None, mcp_url: str = None):
    """初始化上下文。data_dir 缺省取 ARCH_DATA_DIR / ~/.topocode。"""
    global _db, _kb, _data_dir
    from . import db_schema
    from .kb_gateway import KbGateway
    data_dir = data_dir or default_data_dir()
    if data_dir != _data_dir:
        # 数据目录变更(测试重设) → 丢弃项目库连接缓存
        with _project_lock:
            _project_dbs.clear()
        _data_dir = data_dir
    os.makedirs(data_dir, exist_ok=True)
    if _kb is None:
        _kb = KbGateway(base_url=kb_url, mcp_url=mcp_url)
    if _db is None:
        from topoone.db.manager import SQLiteContext
        db_path = os.path.join(data_dir, "architect.db")
        _db = SQLiteContext(db_path, label="architect")
        db_schema.init_architect_db(_db)
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


# ── 项目定位(contextvar) ──────────────────────────────────────

def set_project(project_id: str):
    """设置当前请求的项目 id，返回 token(可用 reset_project 还原)。"""
    return _project_var.set(project_id or None)


def get_project():
    return _project_var.get()


def reset_project(token) -> None:
    try:
        _project_var.reset(token)
    except (ValueError, LookupError):
        pass


# 请求级需求定位(WS 会话消息设置；供 plan agent「定稿」工具定位当前会话需求)
_req_var: contextvars.ContextVar = contextvars.ContextVar(
    "architect_req_id", default=None)


def set_req(req_id: str):
    """设置当前请求的需求 id，返回 token(可用 reset_req 还原)。"""
    return _req_var.set(req_id or None)


def get_req():
    return _req_var.get()


def reset_req(token) -> None:
    try:
        _req_var.reset(token)
    except (ValueError, LookupError):
        pass


# 请求级会话定位(WS 对话设置；供 contract.propose 工具回填 origin.convId 证据链)
_conv_var: contextvars.ContextVar = contextvars.ContextVar(
    "architect_conv_id", default=None)


def set_conv(conv_id: str):
    """设置当前请求的会话 id，返回 token(可用 reset_conv 还原)。"""
    return _conv_var.set(conv_id or None)


def get_conv():
    return _conv_var.get()


def reset_conv(token) -> None:
    try:
        _conv_var.reset(token)
    except (ValueError, LookupError):
        pass


# ── 项目库管理(architect/<pid>/arch.db) ───────────────────────

def project_db_dir() -> str:
    return os.path.join(data_dir(), "architect")


def project_db_path(project_id: str) -> str:
    return os.path.join(project_db_dir(), project_id, "arch.db")


def project_pids_on_disk() -> list:
    """磁盘上已存在的各项目库(目录名即项目 id)。"""
    out = []
    for f in glob.glob(os.path.join(project_db_dir(), "*", "arch.db")):
        out.append(os.path.basename(os.path.dirname(f)))
    return sorted(out)


def project_db(project_id: str, create: bool = True):
    """项目库连接(LRU 缓存)。create=False 且库不存在 → None。"""
    if not project_id:
        return None
    cached = _project_dbs.get(project_id)
    if cached is not None:
        return cached
    with _project_lock:
        cached = _project_dbs.get(project_id)
        if cached is not None:
            return cached
        path = project_db_path(project_id)
        if not create and not os.path.isfile(path):
            return None
        os.makedirs(os.path.dirname(path), exist_ok=True)
        from topoone.db.manager import SQLiteContext
        from . import db_schema
        cached = SQLiteContext(path, label=f"architect:{project_id}")
        db_schema.init_architect_project_db(cached)
        _project_dbs[project_id] = cached
        return cached


def close_project_db(project_id: str) -> None:
    with _project_lock:
        db = _project_dbs.pop(project_id, None)
    if db is not None:
        try:
            db.close()
        except Exception:
            pass


def delete_project_db(project_id: str) -> None:
    """删除项目库(删项目用): 关连接 + 删文件 + 清空目录。"""
    close_project_db(project_id)
    path = project_db_path(project_id)
    try:
        if os.path.isfile(path):
            os.remove(path)
        for suffix in ("-wal", "-shm"):
            p = path + suffix
            if os.path.isfile(p):
                os.remove(p)
        d = os.path.dirname(path)
        if os.path.isdir(d) and not os.listdir(d):
            os.rmdir(d)
    except OSError:
        pass
