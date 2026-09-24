"""图编辑器多轮会话路由（MS5-V2 自 viewer.py 切分；独立 diagram-editor.log）。"""
import hashlib
import json
import logging
import logging.handlers
import os
import re
import time as _time

from fastapi import APIRouter, HTTPException, Request

from topoone import service_common as common

router = APIRouter()

# ── File logger for diagram editor (not to console) ──
_diag_log = logging.getLogger(__name__ + ".diagram_editor")
_diag_log.setLevel(logging.DEBUG)
_diag_log.propagate = False
_log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "logs")
os.makedirs(_log_dir, exist_ok=True)
_log_path = os.path.join(_log_dir, "diagram-editor.log")
_fh = logging.handlers.RotatingFileHandler(_log_path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
_fh.setLevel(logging.DEBUG)
_fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
_diag_log.addHandler(_fh)

logger = logging.getLogger(__name__)

# ── Diagram Editing Agent (Scheme B) ──

import time as _time


def _make_message_id() -> str:
    return "msg_" + hashlib.md5(str(_time.time_ns()).encode()).hexdigest()[:16]


def _summarize_tool_result(t_name: str, result: dict) -> str:
    if "code" in result:
        v = result.get("validation", {})
        return f"code_len={len(result['code'])} valid={v.get('valid')} errors={v.get('errors', [])[:2]}"
    if "ir" in result:
        ir = result.get("ir", {})
        ns = len(ir.get("nodes", []) or ir.get("participants", []) or ir.get("classes", []))
        es = len(ir.get("edges", []) or ir.get("messages", []) or ir.get("relations", []))
        sg = len(ir.get("subgraphs", []) or [])
        return f"nodes={ns} edges={es} subgraphs={sg}"
    if result.get("stats"):
        s = result["stats"]
        return f"nodes={s.get('node_count')} edges={s.get('edge_count')} chars={s.get('char_count')}"
    if "errors" in result:
        return f"errors={result['errors'][:3]}"
    if "error" in result:
        return f"error={result['error'][:120]}"
    return f"keys={list(result.keys())[:4]}"


@router.post("/api/diagram-editor/process")
async def diagram_editor_process(request: Request):
    _t0 = _time.time()
    try:
        body = await request.json()
        code: str = body.get("code", "")
        lang: str = body.get("lang", "mermaid")
        instruction: str = body.get("instruction", "")
        history: list = body.get("history", [])
        context_limit: int = body.get("context_limit", 0)

        if not code or not instruction:
            _diag_log.warning("missing code or instruction")
            raise HTTPException(400, "code and instruction are required")

        model_id = body.get("model_id", "")
        if not model_id:
            default_row = common.multi_db.main_db.fetchone(
                "SELECT value FROM app_config WHERE key='web_chat_default_model_id'"
            ) if common.multi_db else None
            if default_row and default_row["value"]:
                model_id = default_row["value"]
            else:
                default_model = common.multi_db.main_db.fetchone(
                    "SELECT id FROM model_configs WHERE is_default = 1 AND status = 'connected'"
                ) if common.multi_db else None
                if default_model:
                    model_id = default_model["id"]

        if not model_id:
            _diag_log.warning("no available model")
            raise HTTPException(400, "No available model")

        _diag_log.info("=== diagram-editor process start ===")
        _diag_log.info("model=%s lang=%s code_len=%d instr_len=%d history_entries=%d",
                       model_id, lang, len(code), len(instruction), len(history))
        _diag_log.info("code_preview=%s ...", code[:200].replace("\n", "\\n"))
        _diag_log.info("instruction=%s", instruction[:300])

        from topoone_app_chat.web_tools import get_web_tool_definitions

        diagram_tool_names = [
            "web_diagram_parse",
            "web_diagram_build",
            "web_diagram_validate",
        ]
        tool_defs = get_web_tool_definitions(diagram_tool_names)

        system_prompt = (
            "## 图编辑能力\n"
            "你是图编辑专家。通过三个工具操作 Mermaid/PlantUML 图：\n\n"
            "### 可用工具\n"
            "1. web_diagram_parse —— 将现有图代码解析为结构化中间表示(IR)\n"
            "2. web_diagram_build —— 从 IR 生成语法正确的图代码（唯一能产生代码的工具）\n"
            "3. web_diagram_validate —— 校验图代码语法\n\n"
            "### 工作流程\n"
            "修改现有图：\n"
            "  1. 调用 web_diagram_parse 获取 IR\n"
            "  2. 分析 IR，规划变化\n"
            "  3. 修改 IR 中的字段（在改动的元素上标注 _is_modified: true）\n"
            "  4. 调用 web_diagram_build 生成新代码\n"
            "  5. 调用 web_diagram_validate 确保语法正确\n"
            "  6. 向用户展示修改摘要\n\n"
            "创建新图：\n"
            "  1. 直接构造 IR（含所有节点/边/分组/样式）\n"
            "  2. 调用 web_diagram_build 生成代码\n"
            "  3. 调用 web_diagram_validate 校验\n\n"
            "### 强制约束\n"
            "- 禁止直接输出 mermaid/plantuml 代码。直接输出的代码将被系统自动丢弃。\n"
            "- 所有图代码必须通过 web_diagram_build 工具生成。\n"
            "- LLM 只描述图的结构（在 IR 中表达），不写具体的语法代码。\n"
            "- 每次修改后必须调用 web_diagram_validate。\n"
            "- 对于超大图（char_count > 8000），分区域依次修改。\n\n"
            "### 示例\n"
            "用户：「把用户模块改成蓝色，加一个缓存节点」\n"
            "正确：\n"
            "  1. web_diagram_parse → 获取 IR\n"
            "  2. 修改 IR：user.styles.fill = '#42b883'（标注 _is_modified: true），\n"
            "     添加节点 {id: 'cache', text: 'Redis缓存', shape: 'stadium'}\n"
            "  3. web_diagram_build → 新代码\n"
            "  4. web_diagram_validate → 确认语法正确\n"
            "  5. 输出修改摘要\n\n"
            "错误（将被丢弃）：\n"
            "  直接在回复中写 ```mermaid\\ngraph LR\\n    A[用户模块] --> B[Redis]\\n```\n\n"
            "### IR 格式\n"
            "- nodes: [{id, text, shape, styles, classes, _is_modified}]\n"
            "- edges: [{from, to, label, style, _is_modified}]\n"
            "- subgraphs: [{id, title, nodes, _is_modified}]\n"
            "- direction: TB|LR|RL|BT\n"
            "- init_config: {theme, themeVariables}\n"
            "- 所有 _is_modified: true 的元素会在编辑摘要中展示给用户"
        )

        user_content = f"当前图代码（{lang}）：\n```\n{code}\n```\n\n用户要求：{instruction}"

        model_cfg = common.multi_db.main_db.fetchone(
            "SELECT * FROM model_configs WHERE id = ?", (model_id,)
        ) if common.multi_db else None
        if not model_cfg:
            _diag_log.warning("model config not found: %s", model_id)
            raise HTTPException(400, f"Model {model_id} not found")

        md = dict(model_cfg)
        import requests as _req

        base_url = md.get("url", "").rstrip("/")
        if base_url.endswith("/v1"):
            base_url = base_url[:-3]

        _diag_log.info("model_info: name=%s url=%s timeout=%d max_tokens=%d",
                       md.get("model_name"), base_url, md.get("timeout", 300), md.get("max_tokens", 8192))

        messages = [{"role": "system", "content": system_prompt}]
        for h in history:
            messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})
        messages.append({"role": "user", "content": user_content})

        executor = common.web_tool_executor
        max_rounds = 8
        final_response = ""
        updated_code = code
        code_changed = False

        max_tokens = md.get("max_tokens", 8192)
        if context_limit and context_limit < max_tokens:
            max_tokens = min(context_limit, max_tokens)

        for _round in range(max_rounds):
            _tr0 = _time.time()
            payload = {
                "model": md.get("model_name", ""),
                "messages": messages,
                "tools": tool_defs,
                "tool_choice": "auto",
                "max_tokens": max_tokens,
                "temperature": 0.3,
            }

            extra_raw = md.get("extra_config")
            if extra_raw and isinstance(extra_raw, str):
                try:
                    extra = json.loads(extra_raw)
                    if isinstance(extra, dict):
                        payload.update(extra)
                except Exception:
                    pass

            api_key = md.get("api_key", "")
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}" if api_key else "",
            }

            timeout = md.get('timeout', 300)
            try:
                resp = _req.post(
                    f"{base_url}/v1/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=timeout,
                )
            except _req.exceptions.ConnectionError as e:
                _diag_log.error("round=%d connection_error url=%s: %s", _round + 1, base_url, e)
                raise HTTPException(502,
                    f"无法连接到模型服务 ({base_url})。当前模型 ID: {model_id}")
            except _req.exceptions.Timeout:
                _diag_log.error("round=%d timeout url=%s timeout=%d", _round + 1, base_url, timeout)
                raise HTTPException(504, f"模型服务 ({base_url}) 响应超时 (>{timeout}s)")
            except _req.exceptions.RequestException as e:
                _diag_log.error("round=%d request_error: %s", _round + 1, e)
                raise HTTPException(502, f"模型请求失败: {e}")

            if resp.status_code != 200:
                _diag_log.error("round=%d llm_api_error status=%d body=%s",
                                _round + 1, resp.status_code, resp.text[:200])
                raise HTTPException(502, f"LLM API error: {resp.status_code} {resp.text[:200]}")

            data = resp.json()
            usage = data.get("usage", {})
            choice = data.get("choices", [{}])[0]
            msg = choice.get("message", {})
            content = msg.get("content", "") or ""
            tool_calls = msg.get("tool_calls", [])
            _tr1 = _time.time()
            _round_ms = int((_tr1 - _tr0) * 1000)

            _diag_log.info("[round=%d/%d] llm_time=%dms prompt_tokens=%s completion_tokens=%s content_len=%d tool_calls=%d",
                           _round + 1, max_rounds, _round_ms,
                           usage.get("prompt_tokens", "?"), usage.get("completion_tokens", "?"),
                           len(content), len(tool_calls))

            if content:
                _diag_log.info("[round=%d] llm_reasoning: %s", _round + 1, content[:500])
                final_response = content

            if not tool_calls:
                _diag_log.info("[round=%d] no tool calls — LLM produced final response", _round + 1)
                break

            _tool_t0 = _time.time()
            messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})

            for tc in tool_calls:
                tc_id = tc.get("id", "")
                t_name = tc.get("function", {}).get("name", "")
                try:
                    t_args = json.loads(tc.get("function", {}).get("arguments", "{}"))
                except json.JSONDecodeError:
                    t_args = {}

                _args_preview = json.dumps(t_args, ensure_ascii=False)[:600]
                _diag_log.info("[round=%d] tool_call name=%s args=%s", _round + 1, t_name, _args_preview)

                result = executor.execute(t_name, t_args)
                result_str = json.dumps(result, ensure_ascii=False)
                messages.append({
                    "role": "tool",
                    "content": result_str,
                    "tool_call_id": tc_id,
                    "name": t_name,
                })

                _result_summary = _summarize_tool_result(t_name, result)
                _diag_log.info("[round=%d] tool_result name=%s summary=%s", _round + 1, t_name, _result_summary)

                if t_name == "web_diagram_build" and "code" in result:
                    updated_code = result["code"]
                    code_changed = True
                    _diag_log.info("[round=%d] code UPDATED old_len=%d new_len=%d",
                                   _round + 1, len(code), len(updated_code))

            _tool_t1 = _time.time()
            _diag_log.info("[round=%d] tool_exec_time=%dms", _round + 1, int((_tool_t1 - _tool_t0) * 1000))

        # 从 LLM 响应中剥离图代码块（不再展示给用户）
        if final_response:
            _cleaned = re.sub(r'```(?:mermaid|plantuml)\s*\n.*?\n```', '', final_response, flags=re.DOTALL | re.IGNORECASE).strip()
            if _cleaned != final_response:
                _diag_log.info("stripped code block from LLM response (was %d chars, now %d)", len(final_response), len(_cleaned))
                final_response = _cleaned
            # 兜底：如果没有通过工具生成代码，从响应中提取
            if not code_changed:
                _m = re.search(r'```(mermaid|plantuml)\s*\n(.*?)\n```', final_response, re.DOTALL | re.IGNORECASE)
                if _m:
                    _extracted = _m.group(2).strip()
                    if _extracted:
                        from ..diagram_tools._validator import validate_diagram_syntax
                        _val = validate_diagram_syntax(_extracted, _m.group(1).lower())
                        if _val['valid']:
                            _diag_log.info("code extracted from LLM response (fallback) old_len=%d new_len=%d",
                                           len(code), len(_extracted))
                            updated_code = _extracted
                            code_changed = True

        _total_ms = int((_time.time() - _t0) * 1000)
        _diag_log.info("=== diagram-editor done rounds=%d total=%dms code_changed=%s ===",
                       min(_round + 1, max_rounds), _total_ms, code_changed)

        return {
            "response": final_response,
            "updated_code": updated_code if code_changed else None,
            "code_changed": code_changed,
            "rounds": min(_round + 1, max_rounds),
            "history": messages[-4:],
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("POST /api/diagram-editor/process failed")
        raise HTTPException(500, f"Diagram editor failed: {e}")


@router.post("/api/diagram-tools/apply")
async def diagram_tools_apply(request: Request):
    try:
        body = await request.json()
        sub_session_id = body.get("sub_session_id", "")
        main_session_id = body.get("main_session_id", "")
        msg_id = body.get("msg_id", "")
        diag_id = body.get("diag_id", "")
        lang = body.get("lang", "mermaid")

        from ..diagram_tools._subagent import apply_change, commit_to_main
        if sub_session_id:
            commit_result = commit_to_main(sub_session_id)
        else:
            code = body.get("code", "")
            if not code:
                raise HTTPException(400, "code required")
            commit_result = {"code": code, "modified": True, "diag_id": diag_id}

        return {
            "code": commit_result.get("code", ""),
            "msg_id": commit_result.get("msg_id", msg_id),
            "diag_id": diag_id,
            "modified": commit_result.get("modified", False),
            "lang": lang,
            "_writeback": {
                "msg_id": msg_id,
                "new_code": commit_result.get("code", ""),
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Apply failed: {e}")

