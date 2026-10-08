"""W4 AGENTS.md 规则链（D-2 方案 A，2610-B1）——生成段指纹定界 + 项目规则追加 + 手改保护。

机制：
- 生成段用 HTML 注释定界包裹，begin 标记内嵌生成内容 sha1 指纹
  （markdown 渲染零影响，执行器按普通 md 消费）；
- 项目规则目录 `.topo/rules/*.md`（按名排序、滤缓存后缀）追加在生成段后
  （更近用户；Roo 规则目录纪律的 architect 化）；
- 手改保护（cv-282 问询同精神，不静默覆盖）：旧文件定界段内容 sha1 ≠
  begin 标记存的指纹 → 判手改 → 冲突态返回（force=True 才覆盖）；
  指纹一致 → 属数据驱动的正常再生成，照常覆盖。无定界的旧文件 → 冲突
  （首次迁移 force 一次即入定界形态）。

规则目录变化的追加段是磁盘投影（derived），直接刷新不算手改。
"""
from __future__ import annotations

import hashlib
import os
import re
from typing import Dict, List, Optional, Tuple

_SKIP_SUFFIX = (".log", ".tmp", ".pyc", ".DS_Store")
RULES_DIR = os.path.join(".topo", "rules")
RULES_HEADER = "## 项目规则（.topo/rules/，人工维护）"
_FP_RE = re.compile(r"generated-begin:([0-9a-f]{16})")


def _sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def load_project_rules(root: str) -> List[Tuple[str, str]]:
    """读取 .topo/rules/*.md（按名排序, 滤缓存后缀; 无目录/读失败=空）。"""
    d = os.path.join(root or "", RULES_DIR)
    if not os.path.isdir(d):
        return []
    out: List[Tuple[str, str]] = []
    for name in sorted(os.listdir(d), key=str.lower):
        if not name.endswith(".md") or name.endswith(_SKIP_SUFFIX) or name.startswith("."):
            continue
        try:
            content = open(os.path.join(d, name), encoding="utf-8").read().strip()
        except Exception:  # noqa: BLE001
            continue
        if content:
            out.append((name, content))
    return out


def merge_agents_md(generated: str, root: str) -> str:
    """生成段指纹定界 + 项目规则追加 → 落盘全文。"""
    gen = (generated or "").rstrip()
    parts = [f"<!-- topo:generated-begin:{_sha1(gen)} -->",
             gen, "<!-- topo:generated-end -->"]
    rules = load_project_rules(root)
    if rules:
        parts.append(RULES_HEADER)
        for name, content in rules:
            parts.append(f"### {name}\n\n{content}")
    return "\n\n".join(parts) + "\n"


def _split_generated(text: str) -> Tuple[Optional[str], str]:
    """返回 (begin 标记, 定界段内容)；无定界 → (None, 全文)。"""
    begin = end = -1
    for line in text.splitlines():
        if line.strip().startswith("<!-- topo:generated-begin") and begin < 0:
            begin = text.index(line)
            begin_marker = line.strip()
        if line.strip() == "<!-- topo:generated-end -->":
            end = text.index(line)
    if begin < 0 or end < 0:
        return None, text
    body = text[text.index("\n", begin) + 1:end].rstrip("\n")
    return begin_marker, body


def detect_manual_edit(old: Optional[str], fresh_merged: str) -> Dict[str, object]:
    """旧文件 vs 新生成全文 → {status: clean|conflict, manual_excerpt}。

    clean = 可安全刷新（旧文件定界段未被手改/内容幂等/纯规则投影变化）；
    conflict = 定界段被手改（或旧文件无定界标记）→ 调用方问询，force 才覆盖。
    """
    if old is None:
        return {"status": "clean"}
    marker, body = _split_generated(old)
    if marker is None:
        return {"status": "conflict",
                "manual_excerpt": old.strip()[:120]}       # 旧形态整文件视同手改
    m = _FP_RE.search(marker or "")
    stored = m.group(1) if m else ""
    if stored and _sha1(body.strip()) == stored:
        return {"status": "clean"}                          # 数据驱动再生成
    return {"status": "conflict", "manual_excerpt": body[:120]}
