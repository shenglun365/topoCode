"""
统一日志配置

- 按日期+时间戳+类别分文件
- TimedRotatingFileHandler 自动轮转
- 环境变量控制级别和目录
- 统一格式

环境变量:
  TOPOCODE_LOG_DIR=~/.topoone/logs
  TOPOCODE_LOG_LEVEL=DEBUG|INFO|WARN|ERROR
"""
import logging
import os
import sys
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler

from config import LOG_DIR, LOG_LEVEL

# 日志类别到模块前缀的映射
LOG_CATEGORIES = {
    'backend': ['core_service', 'task_manager', 'sqlite_ctx', 'plantuml_service'],
    'parsers': ['parsers.', 'analyst_runner', 'community_analysis'],
    'zmq': ['zmq_server', 'rpc_server'],
}

# 统一日志格式
LOG_FORMAT = '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

# 日志保留天数
RETENTION_DAYS = 7

# 轮转间隔 (midnight = 每天午夜)
ROTATION_WHEN = 'midnight'
ROTATION_INTERVAL = 1


def _get_log_dir() -> str:
    """获取日志目录，确保存在"""
    log_dir = LOG_DIR
    os.makedirs(log_dir, exist_ok=True)
    return log_dir


def _get_timestamp() -> str:
    """获取当前时间戳字符串"""
    return datetime.now().strftime('%Y-%m-%d_%H%M%S')


def _get_log_file(log_dir: str, category: str) -> str:
    """生成日志文件路径"""
    timestamp = _get_timestamp()
    return os.path.join(log_dir, f'{timestamp}_{category}.log')


def _create_file_handler(log_file: str) -> TimedRotatingFileHandler:
    """创建文件处理器"""
    handler = TimedRotatingFileHandler(
        log_file,
        when=ROTATION_WHEN,
        interval=ROTATION_INTERVAL,
        backupCount=RETENTION_DAYS,
        encoding='utf-8',
    )
    handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    return handler


def _get_category_for_logger(logger_name: str) -> str:
    """根据 logger 名称确定日志类别"""
    for category, prefixes in LOG_CATEGORIES.items():
        for prefix in prefixes:
            if logger_name.startswith(prefix):
                return category
    return 'backend'  # 默认类别


def setup_logging(level_str: str = None, log_dir: str = None) -> None:
    """
    初始化统一日志系统

    Args:
        level_str: 日志级别字符串，默认读取 TOPOCODE_LOG_LEVEL
        log_dir: 日志目录，默认读取 TOPOCODE_LOG_DIR
    """
    # 解析日志级别
    level_str = level_str or LOG_LEVEL
    level = getattr(logging, level_str.upper(), logging.INFO)

    # 获取日志目录
    log_dir = log_dir or _get_log_dir()

    # 清除现有 handlers
    root = logging.getLogger()
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    # 添加标准输出 handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    root.addHandler(console)

    # 设置根级别
    root.setLevel(level)

    # 为每个类别创建文件 handler
    timestamp = _get_timestamp()
    for category in LOG_CATEGORIES:
        log_file = os.path.join(log_dir, f'{timestamp}_{category}.log')
        handler = _create_file_handler(log_file)
        handler.setLevel(level)

        # 为类别中的每个模块添加 handler
        for prefix in LOG_CATEGORIES[category]:
            logger = logging.getLogger(prefix)
            logger.addHandler(handler)

    # 记录日志初始化
    logging.getLogger(__name__).info(
        f'Logging initialized: level={level_str}, dir={log_dir}'
    )
