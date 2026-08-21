"""knowledge.* 知识库命名空间 —— 原 core_service.py 解构（M03 T3.2）。"""

import json
import uuid
from datetime import datetime
from topoone.db.manager import SQLiteContext, MultiDBManager
from topoone.rpc.zmq_server import ZMQServer
def register_knowledge_methods(server: ZMQServer, multi_db: MultiDBManager):
    """注册知识库方法"""
    knowledge_db = multi_db.knowledge_db

    @server.register("knowledge.listDocs")
    def list_docs(search: str = "", dimensions: dict = None, sort_by: str = "updated-desc"):
        query = "SELECT * FROM knowledge_docs WHERE 1=1"
        params = []

        if search:
            query += " AND (title LIKE ? OR description LIKE ?)"
            params.extend([f"%{search}%", f"%{search}%"])

        if sort_by == "created":
            order = "created_at DESC"
        else:
            order = "updated_at DESC"

        query += f" ORDER BY pinned DESC, favorite DESC, {order}"

        rows = knowledge_db.fetchall(query, tuple(params))
        for row in rows:
            if row.get("tags"):
                row["tags"] = json.loads(row["tags"])
        return rows

    @server.register("knowledge.createDoc")
    def create_doc(title: str, content: str = "", project_id: str = None, tags: dict = None, type: str = "document"):
        doc_id = f"doc-{uuid.uuid4().hex[:8]}"
        now = datetime.now().isoformat()

        knowledge_db.insert("knowledge_docs", {
            "id": doc_id,
            "title": title,
            "type": type,
            "description": content[:200] if content else "",
            "content": content,
            "project_id": project_id,
            "tags": json.dumps(tags or {}),
            "status": "draft",
            "created_at": now,
            "updated_at": now,
        })

        return knowledge_db.fetchone("SELECT * FROM knowledge_docs WHERE id = ?", (doc_id,))

    @server.register("knowledge.getDoc")
    def get_doc(id: str):
        row = knowledge_db.fetchone("SELECT * FROM knowledge_docs WHERE id = ?", (id,))
        if row and row.get("tags"):
            row["tags"] = json.loads(row["tags"])
        return row

    @server.register("knowledge.updateDoc")
    def update_doc(id: str, **kwargs):
        allowed = {"content", "tags", "status", "favorite", "pinned", "title", "description"}
        data = {k: v for k, v in kwargs.items() if k in allowed}
        if "tags" in data:
            existing = knowledge_db.fetchone("SELECT tags FROM knowledge_docs WHERE id = ?", (id,))
            if existing and existing.get("tags"):
                existing_tags = json.loads(existing["tags"])
                existing_tags.update(data["tags"])
                data["tags"] = json.dumps(existing_tags)
            else:
                data["tags"] = json.dumps(data["tags"])
        data["updated_at"] = datetime.now().isoformat()

        knowledge_db.update("knowledge_docs", data, "id = ?", (id,))
        return get_doc(id)

    @server.register("knowledge.deleteDoc")
    def delete_doc(id: str):
        knowledge_db.delete("knowledge_docs", "id = ?", (id,))

    @server.register("knowledge.getGraph")
    def get_graph(project_id: str = None):
        docs = knowledge_db.fetchall("SELECT id, title, type, tags FROM knowledge_docs")
        nodes = []
        edges = []

        for doc in docs:
            tags = json.loads(doc.get("tags") or "{}")
            nodes.append({
                "id": doc["id"],
                "label": doc["title"],
                "type": doc["type"],
                "category": "document",
            })
            for category, tag_list in tags.items():
                for tag in (tag_list or []):
                    tag_id = f"tag-{category}-{tag}"
                    if not any(n["id"] == tag_id for n in nodes):
                        nodes.append({
                            "id": tag_id,
                            "label": tag,
                            "type": "tag",
                            "category": category,
                        })
                    edges.append({
                        "source": doc["id"],
                        "target": tag_id,
                        "type": "tagged",
                    })

        return {"nodes": nodes, "edges": edges}

    @server.register("knowledge.getDimensions")
    def get_dimensions():
        docs = knowledge_db.fetchall("SELECT tags FROM knowledge_docs")
        dimensions = {
            "lifecycle": set(),
            "techStack": set(),
            "abstraction": set(),
            "purpose": set(),
        }

        for doc in docs:
            if doc.get("tags"):
                tags = json.loads(doc["tags"])
                for key in dimensions:
                    if key in tags and tags[key]:
                        dimensions[key].update(tags[key])

        return {k: sorted(v) for k, v in dimensions.items()}

    return server


# ==================== 设置配置方法 ====================
