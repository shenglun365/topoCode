"""
SubAgent — 一次性文件探索 + 摘要子任务。

独立 LLM 上下文，不污染主会话。
对每个文件：检查缓存 → 未命中则读取 + LLM 摘要 → 缓存。
并行处理多个文件（I/O 并行，LLM 串行）。
"""

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# 摘要质量最低要求（字符数）
_MIN_SUMMARY_LEN = 30

# 文件大小阈值：超过此值使用 AST 结构化提取
_FILE_SIZE_THRESHOLD = 10000

_KIND_LABELS = {
    "function": "函数", "method": "方法", "class": "类",
    "struct": "结构体", "enum": "枚举", "interface": "接口",
    "variable": "变量", "import": "导入", "field": "字段",
    "property": "属性",
}

_MAX_PER_KIND = 30  # 结构化展示时每类最多展示的符号数


@dataclass
class SubAgentResult:
    files_processed: int
    cache_hits: int
    cache_misses: int
    summaries: list           # [{path, summary, cached, cached_at}]
    tokens_used: int
    tokens_saved: int          # 因缓存命中节省的估算 token


def _is_valid_summary(summary: str) -> bool:
    """判断摘要质量是否达到缓存标准。"""
    if not summary:
        return False
    if len(summary) < _MIN_SUMMARY_LEN:
        return False
    # 排除错误占位符
    bad_markers = ["(无法读取)", "摘要失败", "无法读取文件"]
    return not any(m in summary for m in bad_markers)


class SubAgent:
    """执行单次文件批处理 + 摘要任务。"""

    def __init__(self, multi_db, project_root: str = "", model_id: str = "",
                 project_db=None, task_id: str = ""):
        self._multi_db = multi_db
        self._project_root = project_root
        self._model_id = model_id
        self._project_db = project_db
        self._task_id = task_id

    async def summarize_files(
        self,
        files: list[str],
        task_id: str,
        project_id: str,
        file_cache,               # FileSummaryCache
        focus: str = "",
        max_concurrent: int = 1,
        force_refresh: bool = False,
    ) -> SubAgentResult:
        """并行读取文件并摘要。上限 10 个文件。

        Args:
            files: 文件路径列表（绝对路径）
            task_id: 任务 ID
            project_id: 项目 ID
            file_cache: FileSummaryCache 实例
            focus: 摘要侧重点
            max_concurrent: 最大并发读取数
            force_refresh: 强制忽略缓存，重新摘要
        """
        unique = list(dict.fromkeys(files))[:10]

        total_tokens = 0
        cache_hits = 0
        cache_misses = 0
        total_read_chars = 0
        summaries = []

        sem = asyncio.Semaphore(max_concurrent)
        lock = asyncio.Lock()

        async def _read_or_cache(fp: str):
            nonlocal cache_hits, cache_misses, total_tokens, total_read_chars

            rel = os.path.relpath(fp, self._project_root) if self._project_root else fp

            # 缓存命中（force_refresh 时跳过）
            if not force_refresh:
                cached = file_cache.get(rel)
                if cached:
                    summary = cached["summary"]
                    if _is_valid_summary(summary):
                        cache_hits += 1
                        logger.info(
                            f"[FileCache] HIT: {rel} (summary_len={len(summary)}, "
                            f"cached_at={cached.get('created_at','?')})"
                        )
                        return {
                            "path": fp, "summary": summary, "cached": True,
                            "cached_at": cached.get("created_at", ""),
                        }
                    else:
                        logger.warning(
                            f"[FileCache] INVALID: {rel} (len={len(summary)}), "
                            f"will re-summarize"
                        )

            cache_misses += 1

            # ── 按文件大小分流: >10KB + AST 有数据 → 结构化提取 ──
            if self._should_use_structure(fp):
                logger.info(f"[FileCache] MISS: {rel} → 结构化提取 (AST)")
                header = self._read_file_header(fp, 2000)
                structure = self._extract_structure(fp)
                if structure:
                    edges = self._extract_call_edges(fp)
                    text = self._build_structure_text(structure, header or "", edges)
                    async with lock:
                        total_read_chars += len(text)
                        total_tokens += len(text) // 4
                    async with sem:
                        try:
                            summary, tokens = await self._summarize(
                                text, rel, focus, is_structure=True)
                            async with lock:
                                total_tokens += tokens or 0
                        except Exception as e:
                            logger.warning(f"[FileCache] SUMMARIZE-ERR: {rel}: {e}")
                            summary = f"摘要失败: {e}"
                else:
                    # AST 无数据，回退到文件读取
                    logger.info(f"[FileCache] MISS: {rel} → AST 无数据, 回退全文读取")
                    content = await asyncio.to_thread(self._read_file, fp)
                    if content is None:
                        return {"path": fp, "summary": "(无法读取)", "cached": False,
                                "cached_at": ""}
                    async with lock:
                        total_read_chars += len(content)
                        total_tokens += len(content) // 4
                    async with sem:
                        try:
                            summary, tokens = await self._summarize(content, rel, focus)
                            async with lock:
                                total_tokens += tokens or 0
                        except Exception as e:
                            summary = f"摘要失败: {e}"
            else:
                # ≤ 10KB → 直接读取文件
                logger.info(f"[FileCache] MISS: {rel} → reading + LLM摘要")
                content = await asyncio.to_thread(self._read_file, fp)
                if content is None:
                    logger.warning(f"[FileCache] READ-ERR: {rel} (file not found)")
                    return {"path": fp, "summary": f"(无法读取)", "cached": False,
                            "cached_at": ""}
                async with lock:
                    total_read_chars += len(content)
                    total_tokens += len(content) // 4
                async with sem:
                    try:
                        summary, tokens = await self._summarize(content, rel, focus)
                        async with lock:
                            total_tokens += tokens or 0
                    except Exception as e:
                        logger.warning(f"[FileCache] SUMMARIZE-ERR: {rel}: {e}")
                        summary = f"摘要失败: {e}"

            # 缓存（通过质量校验才写入）
            if _is_valid_summary(summary):
                try:
                    file_cache.put(rel, task_id, summary)
                    logger.info(f"[FileCache] CACHED: {rel} (summary_len={len(summary)})")
                except Exception as e:
                    logger.warning(f"[FileCache] CACHE-WRITE-ERR: {rel}: {e}")
            else:
                logger.warning(f"[FileCache] SKIP-CACHE: {rel} (bad summary: {summary[:80]})")

            return {"path": fp, "summary": summary, "cached": False, "cached_at": ""}

        results = await asyncio.gather(*[_read_or_cache(f) for f in unique])

        # 估算缓存节省的 token（每个文件约 8000/4 + 200/4 ≈ 2050 tokens）
        avg_tokens_per_file = 2050
        tokens_saved = cache_hits * avg_tokens_per_file

        logger.info(
            f"[FileCache] batch: {len(unique)} files, "
            f"HIT={cache_hits}, MISS={cache_misses}, "
            f"tokens_saved≈{tokens_saved}, tokens_used={total_tokens}"
        )

        return SubAgentResult(
            files_processed=len(unique),
            cache_hits=cache_hits,
            cache_misses=cache_misses,
            summaries=results,
            tokens_used=total_tokens,
            tokens_saved=tokens_saved,
        )

    def _read_file(self, path: str) -> Optional[str]:
        """同步读取文件内容（上限 10000 字符）。由 asyncio.to_thread 包装。"""
        abs_path = path
        if self._project_root and not os.path.isabs(path):
            abs_path = os.path.join(self._project_root, path)
        if not os.path.isfile(abs_path):
            return None
        try:
            with open(abs_path, "r", encoding="utf-8") as f:
                content = f.read(10000)
        except (UnicodeDecodeError, LookupError):
            try:
                with open(abs_path, "r", encoding="latin-1") as f:
                    content = f.read(10000)
            except Exception:
                return None
        if len(content) >= 10000:
            content += "\n\n...（文件过长已截断）"
        return content

    def _read_file_header(self, path: str, max_chars: int = 2000) -> str:
        """读取文件头部（注释+imports），最多 max_chars 字符。"""
        content = self._read_file(path)
        if not content:
            return ""
        return content[:max_chars]

    def _get_file_size(self, path: str) -> int:
        """获取文件大小 (优先 source_files 表, 否则 os.path.getsize)"""
        try:
            if self._project_db:
                row = self._project_db.execute(
                    "SELECT size FROM source_files WHERE file_path=? LIMIT 1", (path,)
                ).fetchone()
                if row and row["size"]:
                    return row["size"]
            if os.path.isfile(path):
                return os.path.getsize(path)
        except Exception:
            pass
        return 0

    def _should_use_structure(self, path: str) -> bool:
        """文件 > 10KB 且 graph_node 有数据 → 使用结构化提取"""
        size = self._get_file_size(path)
        if size <= _FILE_SIZE_THRESHOLD:
            return False
        if not self._project_db or not self._task_id:
            return False
        try:
            row = self._project_db.execute(
                "SELECT COUNT(*) as cnt FROM graph_node WHERE task_id=? AND file_path=?",
                (self._task_id, path)
            ).fetchone()
            return bool(row and row["cnt"] > 0)
        except Exception:
            return False

    def _extract_structure(self, path: str) -> Optional[dict]:
        """从 graph_node 提取文件符号结构，按 kind 分组。"""
        if not self._project_db or not self._task_id:
            return None
        try:
            rows = self._project_db.execute(
                "SELECT id, kind, name, signature, start_line, end_line, "
                "docstring, visibility, is_exported, qualified_name "
                "FROM graph_node WHERE task_id=? AND file_path=? "
                "ORDER BY start_line",
                (self._task_id, path)
            ).fetchall()
            if not rows:
                return None
            symbols = [dict(r) for r in rows]
            grouped: dict[str, list] = {}
            for s in symbols:
                kind = s.get("kind", "unknown")
                grouped.setdefault(kind, []).append(s)
            return {"file_path": path, "symbol_count": len(symbols), "by_kind": grouped}
        except Exception:
            return None

    def _extract_call_edges(self, path: str) -> list[str]:
        """提取本文件内符号间的依赖/调用关系。最多 50 条。"""
        if not self._project_db or not self._task_id:
            return []
        try:
            rows = self._project_db.execute(
                "SELECT g1.name as src, g2.name as tgt, d.type "
                "FROM dependencies d "
                "JOIN graph_node g1 ON g1.id = d.source_id AND g1.task_id = ? "
                "JOIN graph_node g2 ON g2.id = d.target_id AND g2.task_id = ? "
                "WHERE g1.file_path = ? AND g2.file_path = ? "
                "LIMIT 50",
                (self._task_id, self._task_id, path, path)
            ).fetchall()
            return [f"{r['src']} → {r['tgt']}" + (f" ({r['type']})" if r.get('type') else "")
                    for r in rows]
        except Exception:
            return []

    def _extract_sub_members(self, parent_id: str) -> list[str]:
        """获取父符号 (类/结构体) 的子成员 (方法/字段)。"""
        if not self._project_db:
            return []
        try:
            rows = self._project_db.execute(
                "SELECT kind, name, signature FROM graph_node "
                "WHERE qualified_name LIKE ? AND kind IN ('method','field','property') "
                "LIMIT 50",
                (f"%{parent_id}%",)
            ).fetchall()
            return [f"{r['kind']}: {r['name']} `{r['signature'][:80]}`" if r.get('signature')
                    else f"{r['kind']}: {r['name']}"
                    for r in rows]
        except Exception:
            return []

    def _build_structure_text(self, structure: dict, header: str,
                              edges: list[str]) -> str:
        """将结构化数据转为 LLM 友好的 Markdown 文本。"""
        rel_path = os.path.relpath(structure["file_path"], self._project_root) \
            if self._project_root else structure["file_path"]

        lines = [
            f"## 文件符号结构: {rel_path}  ({structure['symbol_count']} 个符号)\n",
        ]
        if header:
            lines.append(f"### 文件头部\n```\n{header.strip()[:2000]}\n```\n")

        for kind, kind_symbols in structure["by_kind"].items():
            count = len(kind_symbols)
            label = _KIND_LABELS.get(kind, kind)
            lines.append(f"### {label} ({count})")
            for s in kind_symbols[:_MAX_PER_KIND]:
                name = s.get("name", "")
                sid = s.get("id", "")
                sig = (s.get("signature") or "")[:120]
                doc = (s.get("docstring") or "")[:80]
                vis = s.get("visibility", "")
                is_exp = "导出" if s.get("is_exported") else ""
                line_range = f"L{s.get('start_line', '?')}-{s.get('end_line', '?')}"
                parts = [f"`{name}`"]
                if sid:
                    parts.append(f"id={sid}")
                parts.append(line_range)
                if sig:
                    parts.append(f"`{sig}`")
                extras = " ".join(filter(None, [vis, is_exp]))
                if extras:
                    parts.append(extras)
                lines.append("- " + " | ".join(parts))
                if kind in ("class", "struct") and sid:
                    subs = self._extract_sub_members(sid)
                    if subs:
                        for sub in subs:
                            lines.append(f"    - {sub}")
                if doc:
                    lines.append(f"     doc: \"{doc}\"")
            if count > _MAX_PER_KIND:
                lines.append(f"  ... 还有 {count - _MAX_PER_KIND} 个 {label}")
            lines.append("")

        if edges:
            lines.append(f"### 内部调用关系 ({len(edges)} 条)")
            for e in edges[:30]:
                lines.append(f"- {e}")

        lines.append(
            "\n> 使用 get_symbol_code(file_path=\"...\", name=\"符号名\") "
            "获取完整代码。"
            " 使用 get_symbol_detail(symbol_id=\"...\") 查看元数据。"
        )
        return "\n".join(lines)

    async def _summarize(self, content: str, filepath: str, focus: str = "",
                         is_structure: bool = False) -> tuple[str, int]:
        """调用 LLM 对文件内容进行结构化摘要。"""
        if is_structure:
            intro = (
                "你是代码分析助手。以下是文件的 AST 符号结构（含签名、文档注释、调用关系），"
                "请生成一段简洁的摘要（200 字以内），"
                "列出文件的主要功能、关键函数/类以及依赖关系。\n\n"
            )
        else:
            intro = (
                "你是代码分析助手。请根据以下文件内容，生成一段简洁的摘要（200 字以内），"
                "列出文件的主要功能、关键函数/类以及依赖关系。\n\n"
            )
        prompt = intro
        if focus:
            prompt += f"摘要侧重点: {focus}\n\n"
        prompt += f"文件路径: {filepath}\n"
        content_label = "文件符号结构" if is_structure else "文件内容"
        prompt += f"{content_label}:\n```\n{content[:40000]}\n```\n\n"
        prompt += "请用中文输出摘要："

        model = self._model_id
        if not model:
            from .tool_calling.strategy import _resolve_model_id
            model = _resolve_model_id(self._multi_db)
        if not model:
            raise RuntimeError("无法解析摘要模型 ID")

        from llm_service import LLMService
        service = LLMService(self._multi_db)
        summary = await service.sync_chat(
            messages=[{"role": "user", "content": prompt}],
            model_id=model,
        )
        summary_text = (summary or "").strip()[:2000]
        est_tokens = len(prompt) // 4 + len(summary_text) // 4
        return summary_text, est_tokens
