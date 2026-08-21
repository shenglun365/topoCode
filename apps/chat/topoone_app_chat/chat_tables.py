"""chat 专属表初始化（M12，自 service_common._ensure_chat_tables 迁出）。

chat.db 建表由 MultiDBManager 初始化时统一建立（CHAT_DB_TABLES_SQL）；
此处保留 chat_notes → chat_drafts 的旧数据迁移（防御性 no-op 兼容）。
"""

import logging

logger = logging.getLogger(__name__)


def ensure_chat_tables(multi_db):
    """chat.db 旧表迁移（chat_notes → chat_drafts）。表结构由 MultiDBManager 建立。"""
    if not multi_db:
        return
    chat_db = getattr(multi_db, "chat_db", None)
    if chat_db is None:
        return
    try:
        # 兼容旧数据: chat_notes → chat_drafts 迁移（若 chat.db 中存在旧表名）
        _old = chat_db.fetchone(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='chat_notes'"
        )
        _new = chat_db.fetchone(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='chat_drafts'"
        )
        if _old and not _new:
            chat_db.execute("ALTER TABLE chat_notes RENAME TO chat_drafts")
            logger.info("[chat] migrated chat_notes → chat_drafts")
    except Exception as e:
        logger.warning(f"[chat] chat_notes→chat_drafts migration skipped: {e}")
