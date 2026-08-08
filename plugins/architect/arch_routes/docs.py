"""Docs routes — 本地 md 文档只读预览。

使用文档/教程(md 文档)经本域提供只读内容, 前端用 MarkdownView 渲染:
  GET /docs/list               → 文档目录(名称/文件/标题)
  GET /docs/{doc_id}           → 原始 markdown 内容(只读, 不支持写)

文档源: 仓库根 `docs/architect/*.md`。解析失败/文件不存在 → 404。
路径越权防护: 只允许 `[A-Za-z0-9_-]+.md` 白名单, 拒绝 `..`/绝对路径。
"""
import os
import re
from fastapi import APIRouter, HTTPException
from .common import ok

router = APIRouter()

_DOC_ID_RE = re.compile(r"^[A-Za-z0-9_\-]+$")


def _docs_dir() -> str:
    """仓库根 docs/architect。经 plugins/architect → 仓库根回溯。"""
    here = os.path.dirname(os.path.abspath(__file__))
    # plugins/architect/arch_routes → 上溯 3 级到仓库根
    repo = os.path.abspath(os.path.join(here, "..", "..", ".."))
    docs = os.path.join(repo, "docs", "architect")
    if not os.path.isdir(docs):
        return ""
    return docs


def list_docs() -> list:
    docs = _docs_dir()
    if not docs:
        return []
    out = []
    for name in sorted(os.listdir(docs)):
        if not name.endswith(".md"):
            continue
        doc_id = name[:-3]
        path = os.path.join(docs, name)
        title = _first_heading(path) or doc_id
        out.append({
            "id": doc_id,
            "file": name,
            "title": title,
        })
    return out


def _first_heading(path: str) -> str:
    try:
        with open(path, "r", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line.startswith("# "):
                    return line[2:].strip()
                if line.startswith("#"):
                    return line.lstrip("#").strip()
                if line:
                    # 首行非标题 → 截取前 40 字符作标题
                    return line[:40].strip()
    except OSError:
        return ""
    return ""


def read_doc(doc_id: str) -> str:
    if not _DOC_ID_RE.match(doc_id):
        raise HTTPException(status_code=404, detail="invalid doc id")
    docs = _docs_dir()
    if not docs:
        raise HTTPException(status_code=404, detail="docs not found")
    path = os.path.join(docs, f"{doc_id}.md")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="doc not found")
    try:
        with open(path, "r", errors="replace") as f:
            return f.read()
    except OSError as e:
        raise HTTPException(status_code=404, detail=f"read failed: {e}")


@router.get("/docs/list")
async def docs_list():
    return ok(list_docs())


@router.get("/docs/{doc_id}")
async def docs_get(doc_id: str):
    return ok({"id": doc_id, "content": read_doc(doc_id)})
