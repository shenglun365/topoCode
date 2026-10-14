"""引用(ref)解析族（MS5-V3 重做）。"""
import logging

from topoone.db.manager import MultiDBManager

from .defs import MAX_RESULT_LENGTH, _strip_ref_prefix

logger = logging.getLogger(__name__)


def resolve_refs_to_context(refs: list[dict], multi_db: MultiDBManager) -> str:
    """将 refs 列表解析为注入用的 system message 内容"""
    parts = []
    for ref in refs:
        t = ref.get("type")
        label = ref.get("label", "")
        handler = _REF_RESOLVERS.get(t)
        if handler:
            try:
                text = handler(ref, multi_db)
                if text:
                    parts.append(text)
            except Exception as e:
                parts.append(f"引用「{label}」加载失败: {e}")
        elif not t:
            # draft refs（无 type 字段）：直接使用 label + text
            meta = []
            if ref.get("projectName"): meta.append(f"项目:{ref['projectName']}")
            elif ref.get("projectId"): meta.append(f"项目:{ref['projectId'][:12]}")
            if ref.get("taskId"): meta.append(f"任务:{ref['taskId'][:10]}")
            if ref.get("componentId"): meta.append(f"组件:{ref['componentId'][:10]}")
            if label: meta.append(f"来源:{label}")
            s = " | ".join(meta)
            text = ref.get("text", "")
            if text: s += "\n" + text
            if s: parts.append(s)
        else:
            parts.append(f"引用「{label}」")
    return "\n\n".join(parts) if parts else ""


def _resolve_project_ref(ref: dict, multi_db: MultiDBManager) -> str:
    pid = ref.get("id", "")
    row = multi_db.main_db.fetchone("SELECT name, root_path FROM projects WHERE id = ?", (pid,))
    if not row:
        return ""
    return (
        f"用户引用了一个项目「{row['name']}」：\n"
        f"- 根路径: {row['root_path']}\n"
        f"- 项目 ID: {pid}"
    )


def _resolve_task_ref(ref: dict, multi_db: MultiDBManager) -> str:
    tid = ref.get("id", "")
    row = multi_db.main_db.fetchone(
        "SELECT id, name, status, project_id FROM analysis_tasks WHERE id = ?", (tid,)
    )
    if not row:
        return ""
    return (
        f"用户引用了一个分析任务「{row['name']}」(状态: {row['status']})：\n"
        f"- 任务 ID: {tid}\n"
        f"- 项目 ID: {row['project_id']}"
    )


def _resolve_community_doc_ref(ref: dict, multi_db: MultiDBManager) -> str:
    task_id = ref.get("taskId", "")
    comm_id = ref.get("commId", "")
    et = ref.get("edgeType", "CALL")
    inferred = cd._infer_edge_type(comm_id)
    if inferred:
        et = inferred
    label = ref.get("label", comm_id)
    try:
        task = multi_db.main_db.fetchone(
            "SELECT project_id FROM analysis_tasks WHERE id = ?", (task_id,)
        )
        if not task:
            return ""
        pdb = multi_db.get_project_db(task["project_id"])
        row = pdb.fetchone(
            "SELECT name, summary, comm_lv FROM community_llm_results "
            "WHERE task_id=? AND edge_type=? AND comm_id=?",
            (task_id, et, comm_id),
        )
        if row:
            return (
                f"用户引用了社区分析结果「{label}」：\n"
                f"- 层级: {row['comm_lv']}\n"
                f"- 名称: {row['name']}\n"
                f"- 功能摘要: {row['summary']}"
            )
        return f"用户引用了社区「{label}」(暂无 LLM 分析结果)"
    except Exception as e:
        return f"引用社区「{label}」加载失败: {e}"


def _resolve_community_graph_ref(ref: dict, multi_db: MultiDBManager) -> str:
    task_id = ref.get("taskId", "")
    comm_id = ref.get("commId", "")
    et = ref.get("edgeType", "CALL")
    inferred = cd._infer_edge_type(comm_id)
    if inferred:
        et = inferred
    label = ref.get("label", comm_id)
    try:
        task = multi_db.main_db.fetchone(
            "SELECT project_id FROM analysis_tasks WHERE id = ?", (task_id,)
        )
        if not task:
            return ""
        pdb = multi_db.get_project_db(task["project_id"])
        rows = pdb.fetchall(
            "SELECT comm_lv, node_list FROM graph_doc WHERE task_id=? AND edge_type=? AND comm_id=?",
            (task_id, et, comm_id),
        )
        file_count = 0
        node_count = 0
        for r in rows:
            try:
                nodes = json.loads(r["node_list"]) if isinstance(r["node_list"], str) else r["node_list"] or []
                node_count += len(nodes) if isinstance(nodes, list) else 1
            except Exception:
                pass
        return (
            f"用户引用了社区图结构「{label}」：\n"
            f"- 社区 ID: {comm_id}\n"
            f"- 边类型: {et}\n"
            f"- 节点/文件数: ~{node_count}"
        )
    except Exception as e:
        return f"引用社区图「{label}」加载失败: {e}"


def _resolve_source_file_ref(ref: dict, multi_db: MultiDBManager) -> str:
    pid = ref.get("projectId", "")
    path = ref.get("path", "")
    label = ref.get("label", path)
    try:
        proj = multi_db.main_db.fetchone("SELECT root_path FROM projects WHERE id = ?", (pid,))
        if not proj:
            return f"用户引用了文件「{label}」"
        full = os.path.normpath(os.path.join(proj["root_path"], path))
        if os.path.commonpath([full, os.path.normpath(proj["root_path"])]) != os.path.normpath(proj["root_path"]):
            return f"用户引用了文件「{label}」"
        if not os.path.isfile(full):
            return f"用户引用了文件「{label}」(文件不在磁盘)"
        with open(full, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(2000)
        if len(content) >= 2000:
            content += "\n...(截断)"
        return f"用户引用了源码文件「{label}」：\n```\n{content}\n```"
    except Exception:
        return f"用户引用了文件「{label}」"


def _resolve_symbol_ref(ref: dict, multi_db: MultiDBManager) -> str:
    symbol = ref.get("name", "")
    label = ref.get("label", symbol)
    return f"用户引用了符号「{label}」(将在 AI 需要时通过工具查询详情)"


def _resolve_archive_ref(ref: dict, multi_db: MultiDBManager) -> str:
    aid = ref.get("id", "")
    label = ref.get("label", aid)
    row = multi_db.chat_db.fetchone(
        "SELECT title, content, category FROM chat_archives WHERE id = ?", (aid,)
    )
    if not row:
        return f"用户引用了归档知识「{label}」(内容未找到)"
    return (
        f"用户引用了历史归档知识「{row['title']}」(分类: {row['category']})：\n"
        f"{row['content'][:1000]}"
    )


def _resolve_session_ref(ref: dict, multi_db: MultiDBManager) -> str:
    """加载目标会话的消息作为上下文"""
    session_id = ref.get("id", "")
    if not session_id:
        return ""
    sess = multi_db.chat_db.fetchone(
        "SELECT title, project_id FROM llm_sessions WHERE id = ?", (session_id,)
    )
    if not sess:
        logger.info(f"[resolve_session] session={session_id[:12]} not found")
        return f"（会话 {session_id[:12]} 不存在或已被删除）"
    rows = multi_db.chat_db.fetchall(
        "SELECT role, content FROM llm_messages "
        "WHERE session_id = ? ORDER BY created_at LIMIT 50",
        (session_id,),
    )
    logger.info(f"[resolve_session] session={session_id[:12]} title={sess['title']} rows={len(rows)}")
    if not rows:
        return f"（会话 {session_id[:12]}「{sess['title'] or '未命名'}」无消息记录）"
    parts = [f"以下是对话 {session_id[:12]}「{sess['title'] or '未命名'}」的内容："]
    for r in rows:
        role_label = {"user": "用户", "assistant": "AI", "tool": "工具", "system": "系统"}.get(r["role"], r["role"])
        content = (r["content"] or "")[:1000]
        if content:
            parts.append(f"[{role_label}] {content}")
    return "\n".join(parts)


_REF_RESOLVERS = {
    "project": _resolve_project_ref,
    "task": _resolve_task_ref,
    "community_doc": _resolve_community_doc_ref,
    "community_graph": _resolve_community_graph_ref,
    "source_file": _resolve_source_file_ref,
    "symbol": _resolve_symbol_ref,
    "archive": _resolve_archive_ref,
    "session": _resolve_session_ref,
}
