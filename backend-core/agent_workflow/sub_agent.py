"""
SubAgent — 一次性文件探索 + 摘要子任务。

独立 LLM 上下文，不污染主会话。
对每个文件：检查缓存 → 未命中则读取 + LLM 摘要 → 缓存。
并行处理多个文件（I/O 并行，LLM 串行）。
"""

import asyncio
import logging
import os
import threading
from dataclasses import dataclass
from typing import Optional

from state_store import get_store as _get_state_store
from .path_utils import to_abs, to_rel

logger = logging.getLogger(__name__)

# 摘要质量最低要求（字符数）
_MIN_SUMMARY_LEN = 30

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
    failed: int = 0            # 失败文件数（读取/摘要异常）


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

    @classmethod
    def get_failed(cls, task_id: str) -> int:
        return _get_state_store().get_subagent_failed(task_id)

    @classmethod
    def reset_failed(cls, task_id: str):
        _get_state_store().reset_subagent_failed(task_id)

    def __init__(self, multi_db, project_root: str = "", model_id: str = "",
                 project_db=None, task_id: str = "",
                 cancel_event: Optional[threading.Event] = None):
        self._multi_db = multi_db
        self._project_root = project_root
        self._model_id = model_id
        self._project_db = project_db
        self._task_id = task_id
        self._cancel_event = cancel_event or threading.Event()

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
        failed = 0
        total_read_chars = 0
        summaries = []

        sem = asyncio.Semaphore(max_concurrent)
        lock = asyncio.Lock()

        async def _read_or_cache(fp: str):
            nonlocal cache_hits, cache_misses, failed, total_tokens, total_read_chars

            # 取消检查：外层 runtime.cancel() 设置此标志后快速退出
            if self._cancel_event.is_set():
                async with lock:
                    failed += 1
                return {"path": fp, "summary": "(cancelled)", "cached": False, "cached_at": ""}

            # 路径统一：fp 当前为项目相对路径；abs_fp 供文件 I/O / graph_node SQL
            rel = to_rel(fp, self._project_root)
            abs_fp = to_abs(fp, self._project_root)

            # 精确路径未命中 → basename 模糊匹配兜底，同步更新 rel/abs_fp
            if not os.path.isfile(abs_fp) and self._project_root:
                from .path_utils import resolve_file as _resolve_file
                r = _resolve_file(fp, self._project_root)
                if r:
                    abs_fp = r
                    rel = to_rel(r, self._project_root)

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
                header = self._read_file_header(abs_fp, 2000)
                structure = self._extract_structure(abs_fp)
                if structure:
                    edges = self._extract_call_edges(abs_fp)
                    text = self._build_structure_text(structure, header or "", edges)
                    async with lock:
                        total_read_chars += len(text)
                        total_tokens += len(text) // 4
                    async with sem:
                        if self._cancel_event.is_set():
                            async with lock:
                                failed += 1
                            return {"path": fp, "summary": "(cancelled)", "cached": False, "cached_at": ""}
                        try:
                            summary, tokens = await self._summarize(
                                text, rel, focus, is_structure=True)
                            async with lock:
                                total_tokens += tokens or 0
                        except Exception as e:
                            logger.warning(f"[FileCache] SUMMARIZE-ERR: {rel}: {e}")
                            summary = f"摘要失败: {e}"
                            async with lock:
                                failed += 1
                else:
                    # AST 无数据，回退到文件读取
                    logger.info(f"[FileCache] MISS: {rel} → AST 无数据, 回退全文读取")
                    content = await asyncio.to_thread(self._read_file, abs_fp)
                    if content is None:
                        async with lock:
                            failed += 1
                        return {"path": fp, "summary": "(无法读取)", "cached": False,
                                "cached_at": ""}
                    async with lock:
                        total_read_chars += len(content)
                        total_tokens += len(content) // 4
                    async with sem:
                        if self._cancel_event.is_set():
                            async with lock:
                                failed += 1
                            return {"path": fp, "summary": "(cancelled)", "cached": False, "cached_at": ""}
                        try:
                            summary, tokens = await self._summarize(content, rel, focus)
                            async with lock:
                                total_tokens += tokens or 0
                        except Exception as e:
                            logger.warning(f"[FileCache] SUMMARIZE-ERR: {rel}: {e}")
                            summary = f"摘要失败: {e}"
                            async with lock:
                                failed += 1
            else:
                # ≤ 10KB → 直接读取文件
                logger.info(f"[FileCache] MISS: {rel} → reading + LLM摘要")
                content = await asyncio.to_thread(self._read_file, abs_fp)
                if content is None:
                    logger.warning(f"[FileCache] READ-ERR: {rel} (file not found)")
                    async with lock:
                        failed += 1
                    return {"path": fp, "summary": f"(无法读取)", "cached": False,
                            "cached_at": ""}
                async with lock:
                    total_read_chars += len(content)
                    total_tokens += len(content) // 4
                async with sem:
                    if self._cancel_event.is_set():
                        async with lock:
                            failed += 1
                        return {"path": fp, "summary": "(cancelled)", "cached": False, "cached_at": ""}
                    try:
                        summary, tokens = await self._summarize(content, rel, focus)
                        async with lock:
                            total_tokens += tokens or 0
                    except Exception as e:
                        logger.warning(f"[FileCache] SUMMARIZE-ERR: {rel}: {e}")
                        summary = f"摘要失败: {e}"
                        async with lock:
                            failed += 1

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

        # 累积到 StateStore（Phase 0 双写兼容）
        _get_state_store().set_subagent_failed(task_id, _get_state_store().get_subagent_failed(task_id) + failed)

        return SubAgentResult(
            files_processed=len(unique),
            cache_hits=cache_hits,
            cache_misses=cache_misses,
            failed=failed,
            summaries=results,
            tokens_used=total_tokens,
            tokens_saved=tokens_saved,
        )

    def _read_file(self, path: str) -> Optional[str]:
        """同步读取文件内容（上限 10000 字符）。由 asyncio.to_thread 包装。"""
        abs_path = to_abs(path, self._project_root) if self._project_root else path
        if not os.path.isfile(abs_path) and self._project_root:
            from .path_utils import resolve_file
            resolved = resolve_file(path, self._project_root)
            if resolved:
                abs_path = resolved
        if not os.path.isfile(abs_path):
            logger.warning(f"[FileCache] READ-ERR: {path} (file not found)")
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

    def _should_use_structure(self, path: str) -> bool:
        """有 AST 数据时使用结构化提取，无数据时回退全文读取。"""
        if not self._project_db or not self._task_id:
            return False
        try:
            rel_path = to_rel(path, self._project_root)
            row = self._project_db.execute(
                "SELECT COUNT(*) as cnt FROM graph_node WHERE task_id=? AND file_path=?",
                (self._task_id, rel_path)
            ).fetchone()
            return bool(row and row["cnt"] > 0)
        except Exception:
            return False

    def _extract_structure(self, path: str) -> Optional[dict]:
        """从 graph_node 提取文件符号结构，按 kind 分组。path 应为绝对路径。"""
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
        """提取本文件内符号间的依赖/调用关系。最多 50 条。path 应为绝对路径。"""
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
        rel_path = to_rel(structure["file_path"], self._project_root)

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
        # ── 文件元上下文（导出/导入/引用方/类型） ──
        meta_header = ""
        try:
            from context.assembly import CollectContext
            from context.recipes import RECIPE_FILE_SUMMARY
            from context.registry import get_assembler
            mctx = CollectContext(
                db=self._project_db,
                task_id=self._task_id or "",
                project_root=self._project_root,
                file_path=filepath,
            )
            meta_header = get_assembler().assemble(RECIPE_FILE_SUMMARY, mctx)
            if meta_header:
                meta_header += "\n\n"
        except Exception:
            pass

        intro = (
            "你是代码分析助手。请根据以下信息，生成该文件的摘要。"
            "按固定格式输出，每行一条：\n"
            "[类型] module\n"
            "[用途] 一句话说明文件功能（30字内）\n"
            "[导出] 关键函数/类名，逗号分隔\n"
            "[依赖] 外部包或文件依赖\n"
            "[说明] 详细说明功能（100字以内）\n\n"
        )
        prompt = meta_header + intro
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
