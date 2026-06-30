"""
ingest/writer.py — LLM 管线结果写入文件（.tmp → atomic rename → .json）

目录: <project_root>/.topoone/ingest/
文件: <type>-<timestampMs>-<uuid8>.json
"""
import json
import logging
import os
import time
import uuid

logger = logging.getLogger(__name__)

INGEST_DIR_NAME = "ingest"


def _ingest_dir(project_root: str) -> str:
    d = os.path.join(project_root, ".topoone", INGEST_DIR_NAME)
    os.makedirs(d, exist_ok=True)
    return d


def write_ingest(project_root: str, _type: str, data: dict) -> bool:
    """
    写入一条 ingest 记录。
    先写 .tmp → fsync → rename 为 .json，避免消费端读半截文件。

    Args:
        project_root: 项目根目录
        _type: 数据类型 (community_result, subdoc, file_summary, progress)
        data: JSON-serializable dict（必须包含 _type 字段以供消费端识别）

    Returns:
        True 成功, False 失败
    """
    data["_type"] = _type
    ts = int(time.time() * 1000)
    uid = uuid.uuid4().hex[:8]
    basename = f"{_type}-{ts}-{uid}"
    tmp_path = os.path.join(_ingest_dir(project_root), f"{basename}.tmp")
    final_path = os.path.join(_ingest_dir(project_root), f"{basename}.json")

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
