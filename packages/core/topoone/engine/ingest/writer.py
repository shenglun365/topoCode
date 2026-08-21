"""
ingest/writer.py — LLM 管线结果写入文件（.tmp → atomic rename → .json）

目录: {data_dir}/ingest/<project_id>/（中心路径，源码目录不再存放管线数据）
文件: <type>-<timestampMs>-<uuid8>.json
"""
import json
import logging
import os
import time
import uuid

logger = logging.getLogger(__name__)

INGEST_DIR_NAME = "ingest"


def _default_data_dir() -> str:
    return os.environ.get("TOPOCODE_DB_DIR") or os.path.join(os.path.expanduser("~"), ".topocode")


def ingest_dir_for(project_id: str, data_dir: str = "") -> str:
    d = os.path.join(data_dir or _default_data_dir(), INGEST_DIR_NAME, project_id)
    os.makedirs(d, exist_ok=True)
    return d


def write_ingest(project_id: str, _type: str, data: dict, data_dir: str = "") -> bool:
    """
    写入一条 ingest 记录。
    先写 .tmp → fsync → rename 为 .json，避免消费端读半截文件。

    Args:
        project_id: 项目 id
        _type: 数据类型 (community_result, subdoc, file_summary, progress)
        data: JSON-serializable dict（必须包含 _type 字段以供消费端识别）
        data_dir: 数据目录（缺省取 TOPOCODE_DB_DIR / ~/.topocode）

    Returns:
        True 成功, False 失败
    """
    data["_type"] = _type
    ts = int(time.time() * 1000)
    uid = uuid.uuid4().hex[:8]
    basename = f"{_type}-{ts}-{uid}"
    d = ingest_dir_for(project_id, data_dir)
    tmp_path = os.path.join(d, f"{basename}.tmp")
    final_path = os.path.join(d, f"{basename}.json")

    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False, default=str))
            f.flush()
            os.fsync(f.fileno())
        os.rename(tmp_path, final_path)
        return True
    except Exception as e:
        logger.warning(f"[ingest] write failed {_type}: {e}")
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        return False
