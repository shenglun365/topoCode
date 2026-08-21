"""
TopoOne 后端配置文件

ZMQ 端口、SQLite 路径、线程池等全局配置。
所有配置项均可通过环境变量覆盖。
"""
import os

# ==================== ZMQ 配置 ====================
ZMQ_BIND_HOST = os.environ.get("ZMQ_BIND_HOST", "127.0.0.1")
ZMQ_DEALER_PORT = int(os.environ.get("ZMQ_DEALER_PORT", "5671"))
ZMQ_PUB_PORT = int(os.environ.get("ZMQ_PUB_PORT", "5680"))

# RPC 请求超时 (秒)
RPC_TIMEOUT = int(os.environ.get("RPC_TIMEOUT", "30"))

# ==================== SQLite 配置 ====================
# 数据库文件存放目录 (可配置，默认 ~/.topocode)
DB_DIR = os.environ.get(
    "TOPOCODE_DB_DIR",
    os.path.join(os.path.expanduser("~"), ".topocode")
)

# 主库文件名
MAIN_DB_FILE = "topoone.db"

# SQLite PRAGMA 设置
SQLITE_PRAGMAS = {
    "journal_mode": "WAL",
    "busy_timeout": 5000,
    "synchronous": "NORMAL",
    "cache_size": 10000,       # ~10MB
    "foreign_keys": 1,
}

# MultiDBManager LRU 缓存上限
MAX_DB_CONNECTIONS = 3

# ==================== 线程池配置 ====================
PARSE_WORKERS = int(os.environ.get("PARSE_WORKERS", "4"))
PARSE_THREAD_PREFIX = "parse-worker"

# ==================== 解析配置 ====================
MAX_FILE_SIZE = 500 * 1024        # 500KB，超过此大小的文件跳过
MAX_AST_NODES = 100_000           # 单文件最大 AST 节点数
BATCH_INSERT_SIZE = 5000          # 批量插入批次大小

# 进度推送间隔 (每处理 N 个文件推送一次)
PROGRESS_INTERVAL = 5

# ==================== 社区分析配置 ====================
COMMUNITY_MIN_NODE_INCLUDE = 6    # INCLUDE 图最小节点数
COMMUNITY_MIN_NODE_CALL = 12      # CALL 图最小节点数（原20→12，降低粒度）

# 枢纽节点过滤：度 > max(HUB_MIN_DEGREE, total_nodes * HUB_DEGREE_RATIO) 时视为枢纽
HUB_DEGREE_RATIO = 0.3            # 度超过总节点30%
HUB_MIN_DEGREE = 50               # 至少50度才触发（小项目不误判）

# 孤立节点：移除枢纽后，剩余度 ≤ ORPHAN_MAX_DEGREE 视为孤立
ORPHAN_MAX_DEGREE = 0              # 仅移除完全无连接的节点（度为 1 的叶子节点纳入社区检测）

# 同文件内调用降权系数（备选方案）：设为 1.0 = 等同处理，< 1.0 = 降低影响力
INTRAn_FILE_EDGE_WEIGHT = 1.0       # 正常值
INTRAn_FILE_EDGE_FALLBACK_WEIGHT = 0.1  # 备选方案时降权

# ==================== 进程架构模式 ====================
# "monolith" — 单进程模式（默认）：所有 Worker 退化为线程池 / asyncio task，适用于开发/调试
# "distributed" — 多进程模式：AST / LLM / Agent / DB Service 各为独立进程
TOPO_MODE = os.environ.get("TOPO_MODE", "monolith")

# 内部 ZMQ Bus 端口（distributed 模式）
INTERNAL_BUS_PORT = int(os.environ.get("INTERNAL_BUS_PORT", "18760"))
FRONTEND_ZMQ_PORT = int(os.environ.get("FRONTEND_ZMQ_PORT", "18761"))

# DB Service 端口（distributed 模式 — DB Service 监听此端口接收 SQL 请求）
DB_SERVICE_PORT = int(os.environ.get("DB_SERVICE_PORT", "18762"))

# Agent Worker 端口（distributed 模式）
AGENT_WORKER_PORT = int(os.environ.get("AGENT_WORKER_PORT", "18763"))
AGENT_WORKER_PUB_PORT = int(os.environ.get("AGENT_WORKER_PUB_PORT", "18764"))

# ==================== 超大图阈值 ====================
LARGE_GRAPH_NODE_THRESHOLD = 5000

# ==================== 日志配置 ====================
LOG_DIR = os.environ.get("TOPOCODE_LOG_DIR", os.path.join(DB_DIR, "logs"))
LOG_LEVEL = os.environ.get("TOPOCODE_LOG_LEVEL", "INFO")

# ==================== Web Chat 配置 ====================
# 每次消息最多可进行的工具调用轮次
TOOL_ROUND_LIMIT = int(os.environ.get("TOOL_ROUND_LIMIT", "100"))

# 单会话 user+assistant 消息上限（超出后无法继续对话）
SESSION_MAX_MESSAGES = int(os.environ.get("SESSION_MAX_MESSAGES", "200"))
