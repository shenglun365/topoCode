"""KB AST 解析服务化（批2-1）：结构化提取管线的前置数据源。

职责：
- parse_file：单文件 → {symbols, implDetails}（经 KbGateway analysis.parseFileAst，
  内容不落 KB）；implDetails 携带 statements/routes/constants/configKeys——
  结构化骨架（IO 签名/调用序/常量）的直接来源（spike-1 实证：行号/signature 完整）；
- 历史解析（rev 锚定）：KB 按路径读磁盘 → `git show <rev>:<file>` 写临时文件再解析；
- 符号区间索引：行号 → 符号（变化量识别的 hunk→符号映射地基）。

已知边界（spike-1）：Vue SFC 解析弱（仅 setup 顶层变量级）——UI 层资产骨架
产出有限，语义增强(LLM)阶段按需补齐。
"""
from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def parse_file(root: str, rel: str, *, impl: bool = True) -> Optional[dict]:
    """解析工作区文件 → KB parseFileAst 结果（symbols + implDetails）。"""
    full = os.path.join(root, rel.replace("/", os.sep))
    if not os.path.isfile(full):
        return None
    try:
        from ..kb_gateway import call_kb
        res = call_kb("analysis.parseFileAst", filePath=full, file_path=full,
                      implDetails=bool(impl))
        if not (isinstance(res, dict) and res.get("symbols") is not None):
            # 旧 KB 后端不支持 implDetails(HTTP 500) → 无参重试(降级仅符号)
            res = call_kb("analysis.parseFileAst", filePath=full, file_path=full)
        if isinstance(res, dict) and res.get("symbols") is not None:
            return res
        return None
    except Exception as e:
        logger.warning("[structural] parseFileAst %s failed: %s", rel, e)
        return None


def parse_rev_file(root: str, rel: str, rev: str, *, impl: bool = True) -> Optional[dict]:
    """解析历史版本文件（rev 锚定）：`git show <rev>:<rel>` → 临时文件 → parseFileAst。

    rev: 分支名/commit sha/tag。KB 按路径读磁盘，临时文件即任意内容解析通道。
    """
    if not rev or rev == "workspace":
        return parse_file(root, rel, impl=impl)
    try:
        content = subprocess.run(
            ["git", "-C", root, "show", f"{rev}:{rel}"],
            capture_output=True, timeout=30)
        if content.returncode != 0:
            logger.warning("[structural] git show %s:%s failed: %s",
                           rev, rel, content.stderr.decode()[:120])
            return None
        suffix = os.path.splitext(rel)[1] or ".txt"
        with tempfile.NamedTemporaryFile("wb", suffix=suffix, delete=False) as f:
            f.write(content.stdout)
            tmp = f.name
        try:
            from ..kb_gateway import call_kb
            res = call_kb("analysis.parseFileAst", filePath=tmp, file_path=tmp,
                          implDetails=bool(impl))
            if not (isinstance(res, dict) and res.get("symbols") is not None):
                res = call_kb("analysis.parseFileAst", filePath=tmp, file_path=tmp)
            return res if (isinstance(res, dict) and res.get("symbols") is not None) else None
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    except Exception as e:
        logger.warning("[structural] parse rev %s:%s failed: %s", rev, rel, e)
        return None


def symbol_index(parsed: dict) -> List[dict]:
    """解析结果 → 可锚定符号清单（扁平化，含行区间/signature）。

    条目：{name, kind, qualifiedName, startLine, endLine, signature, docstring, isExported}
    行区间 → 符号映射（变化量 hunk 落点判定）直接消费。
    kind 归一化到 architect 锚点白名单口径（function→func、type_alias→interface、
    record→class——_ASSET_EXPECTED_ANCHOR_KIND 用 func/class 等短词）。
    """
    kind_norm = {"function": "func", "method": "method", "type_alias": "interface",
                 "record": "class"}
    out: List[dict] = []
    for s in (parsed or {}).get("symbols") or []:
        if not isinstance(s, dict):
            continue
        kind = (s.get("kind") or "").lower()
        out.append({
            "name": s.get("name") or "",
            "kind": kind_norm.get(kind, kind),
            "qualifiedName": s.get("qualifiedName") or "",
            "startLine": int(s.get("startLine") or 0),
            "endLine": int(s.get("endLine") or 0),
            "signature": s.get("signature") or "",
            "docstring": s.get("docstring") or "",
            "isExported": bool(s.get("isExported")),
        })
    out.sort(key=lambda x: (x["startLine"], -x["endLine"]))
    return out


def symbols_in_range(idx: List[dict], start: int, end: int) -> List[dict]:
    """行区间 [start, end] 命中的符号（区间与符号区间相交；嵌套取最外层即可——
    全量返回由消费方按 kind 过滤）。"""
    hits: List[dict] = []
    for s in idx:
        if s["endLine"] < start or (s["startLine"] > end):
            continue
        if s["startLine"] <= 0:
            continue
        hits.append(s)
    return hits
