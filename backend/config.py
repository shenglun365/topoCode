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
# 数据库文件存放目录 (可配置，默认 ~/.topoone)
DB_DIR = os.environ.get(
    "TOPOCODE_DB_DIR",
    os.path.join(os.path.expanduser("~"), ".topoone")
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
ORPHAN_MAX_DEGREE = 1

# 同文件内调用降权系数（备选方案）：设为 1.0 = 等同处理，< 1.0 = 降低影响力
INTRAn_FILE_EDGE_WEIGHT = 1.0       # 正常值
INTRAn_FILE_EDGE_FALLBACK_WEIGHT = 0.1  # 备选方案时降权

# ==================== 日志配置 ====================
LOG_DIR = os.environ.get("TOPOCODE_LOG_DIR", os.path.join(DB_DIR, "logs"))
LOG_LEVEL = os.environ.get("TOPOCODE_LOG_LEVEL", "INFO")
