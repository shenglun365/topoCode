"""Write proxy for database operations

Single-process mode: executes writes directly on multi_db
Multi-process mode: sends writes through HTTP to BackendApp's Data API
"""

import json
import logging
import os

logger = logging.getLogger(__name__)

# Mode: 'direct' (single process) or 'proxy' (multi process via HTTP)
_mode = 'direct'
_data_api_url = 'http://127.0.0.1:3459'


def configure(mode='direct', data_api_url=None):
    global _mode, _data_api_url
    _mode = mode
    if data_api_url:
        _data_api_url = data_api_url


def execute(db_conn, sql: str, params: tuple = None):
    """Write operation proxy. In direct mode, executes on the local connection.
    
    In proxy mode, this would send the write via HTTP to the Data API.
    For now, always direct since we're still single-process.
    """
    if params:
        return db_conn.execute(sql, params)
    else:
        return db_conn.execute(sql)


def execute_many(db_conn, sql: str, params_list: list):
    """Batch write operation."""
    for params in params_list:
        execute(db_conn, sql, params)
