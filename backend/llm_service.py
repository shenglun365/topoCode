"""LLM 后端服务 — 统一 LLM API 网关

统一入口: llm.chat → streaming_chat() + ZMQ PUB 推送
三模式路由: chat / tools / structured + Prompt 模板 + Tools Calling
"""

import asyncio
import json
import logging
import queue
import threading
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

from zmq_server import ZMQServer
from sqlite_ctx import MultiDBManager

logger = logging.getLogger(__name__)

# ==================== 模型配置读取 ====================

def _get_model_by_id(multi_db: MultiDBManager, model_id: str) -> Optional[Dict[str, Any]]:
    """按 ID 获取模型配置"""
    return multi_db.main_db.fetchone("SELECT * FROM model_configs WHERE id = ?", (model_id,))


# ==================== Session 管理 (SQLite 持久化) ====================

def _make_id() -> str:
    return uuid.uuid4().hex[:12]


# ==================== LLMService 类骨架 ====================

class LLMService:
    """统一 LLM 服务 (session 管理 + streaming_chat + tools + structured)"""

    def __init__(self, multi_db: MultiDBManager):
        self.multi_db = multi_db

    # ==================== Session CRUD ====================

    def list_sessions(
        self,
        module_type: Optional[str] = None,
        project_id: Optional[str] = None,
        status: str = 'active',
    ) -> List[Dict[str, Any]]:
        """列举会话"""
        sessions_db = self.multi_db.sessions_db
        sql = "SELECT * FROM llm_sessions WHERE status = ?"
        params: List[Any] = [status]

        if module_type:
            sql += " AND module_type = ?"
            params.append(module_type)
        if project_id:
            sql += " AND project_id = ?"
            params.append(project_id)

        sql += " ORDER BY updated_at DESC"
        return sessions_db.fetchall(sql, tuple(params))

    def create_session(
        self,
        module_type: str,
        title: str,
        project_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """创建会话"""
        sessions_db = self.multi_db.sessions_db
        # AI 助手会话前缀 ai-，不持久化消息（仅保留调用日志）
        prefix = 'ai-' if module_type == 'ai_assistant' else ''
        session_id = prefix + _make_id()
        now = datetime.now().isoformat()
        meta_json = json.dumps(metadata) if metadata else None

        sessions_db.execute(
            """INSERT INTO llm_sessions (id, module_type, project_id, title, metadata, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (session_id, module_type, project_id, title, meta_json, now, now),
        )
        sessions_db.commit()

        logger.info(f"[LLMService] Session created: id={session_id}, module={module_type}, title={title}")
        return {
            'id': session_id,
            'moduleType': module_type,
            'projectId': project_id,
            'title': title,
            'status': 'active',
            'metadata': metadata,
            'createdAt': now,
            'updatedAt': now,
        }

    def clear_all_sessions(self) -> Dict[str, Any]:
        """清除所有 AI 助手会话"""
        sessions_db = self.multi_db.sessions_db
        sessions_db.execute("PRAGMA foreign_keys = ON")
        # 删除所有非 analysis 关联的会话（analysis_sessions 的外键会级联）
        count = sessions_db.execute("DELETE FROM llm_sessions WHERE module_type = 'ai_assistant'").rowcount
        sessions_db.commit()
        logger.info(f"[LLMService] Cleared {count} AI assistant sessions")
        return {'success': True, 'count': count}

    def delete_session(self, session_id: str) -> Dict[str, Any]:
        """删除会话 (级联删除消息)"""
        sessions_db = self.multi_db.sessions_db
        sessions_db.execute("PRAGMA foreign_keys = ON")

        # 检查会话存在
        row = sessions_db.fetchone("SELECT id FROM llm_sessions WHERE id = ?", (session_id,))
        if not row:
            raise ValueError(f"Session not found: {session_id}")

        sessions_db.execute("DELETE FROM llm_sessions WHERE id = ?", (session_id,))
        sessions_db.commit()

        logger.info(f"[LLMService] Session deleted: id={session_id}")
        return {'success': True}

    def get_messages(
        self,
        session_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """获取会话消息列表"""
        sessions_db = self.multi_db.sessions_db
        return sessions_db.fetchall(
            """SELECT * FROM llm_messages
               WHERE session_id = ?
               ORDER BY created_at ASC
               LIMIT ? OFFSET ?""",
            (session_id, limit, offset),
        )

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        token_count: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """添加消息"""
        sessions_db = self.multi_db.sessions_db
        msg_id = _make_id()
        now = datetime.now().isoformat()
        meta_json = json.dumps(metadata) if metadata else None

        sessions_db.execute(
            """INSERT INTO llm_messages (id, session_id, role, content, token_count, metadata, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (msg_id, session_id, role, content, token_count, meta_json, now),
        )
        # 更新会话时间
        sessions_db.execute(
            "UPDATE llm_sessions SET updated_at = ? WHERE id = ?",
            (now, session_id),
        )
        sessions_db.commit()

        return {
            'id': msg_id,
            'sessionId': session_id,
            'role': role,
            'content': content,
            'tokenCount': token_count,
            'metadata': metadata,
            'createdAt': now,
        }

    def delete_message(self, message_id: str) -> Dict[str, Any]:
        """删除单条消息"""
        sessions_db = self.multi_db.sessions_db
        row = sessions_db.fetchone("SELECT id FROM llm_messages WHERE id = ?", (message_id,))
        if not row:
            raise ValueError(f"Message not found: {message_id}")

        sessions_db.execute("DELETE FROM llm_messages WHERE id = ?", (message_id,))
        sessions_db.commit()
        return {'success': True}

    def update_metadata(
        self,
        session_id: str,
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        """更新会话 metadata (merge 模式)"""
        sessions_db = self.multi_db.sessions_db
        now = datetime.now().isoformat()

        # 读取现有 metadata
        row = sessions_db.fetchone("SELECT metadata FROM llm_sessions WHERE id = ?", (session_id,))
        if not row:
            raise ValueError(f"Session not found: {session_id}")

        existing = {}
        if row and row.get('metadata'):
            try:
                existing = json.loads(row['metadata'])
            except json.JSONDecodeError:
                pass

        # merge
        existing.update(metadata)
        new_meta = json.dumps(existing)

        sessions_db.execute(
            "UPDATE llm_sessions SET metadata = ?, updated_at = ? WHERE id = ?",
            (new_meta, now, session_id),
        )
        sessions_db.commit()

        return {'sessionId': session_id, 'metadata': existing, 'updatedAt': now}

    # ==================== Streaming LLM ====================

    async def streaming_chat(
        self,
        session_id: str,
        messages: List[Dict[str, str]],
        model_id: str,
        mode: str = 'chat',
        tools: Optional[List[str]] = None,
        output_schema: Optional[Dict[str, Any]] = None,
        template_id: Optional[str] = None,
        extra_meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """发起流式 LLM 请求，立即返回 requestId，chunks 通过 ZMQ PUB 推送"""
        from zmq_server import current_call_id
        _cid = current_call_id.get()
        if _cid:
            logger.info(f"[{_cid}] streaming_chat session={session_id} model={model_id} mode={mode} template={template_id}")

        if mode not in ('chat', 'tools', 'structured'):
            raise ValueError(f"Invalid mode: {mode}")

        # 验证模型存在
        model = _get_model_by_id(self.multi_db, model_id)
        if not model:
            raise ValueError(f"Model not found: {model_id}")

        request_id = _make_id()

        # 后台启动流式任务
        task = asyncio.create_task(
            self._execute_streaming(request_id, session_id, messages, model, mode, tools, output_schema, template_id, extra_meta)
        )
        # 存储以便 abort
        if not hasattr(self, '_active_streams'):
            self._active_streams = {}
        self._active_streams[request_id] = task

        logger.info(f"[LLMService] Streaming started: requestId={request_id}, session={session_id}, mode={mode}")
        return {'requestId': request_id, 'status': 'streaming'}

    async def abort_chat(self, request_id: str) -> Dict[str, Any]:
        """中止流式调用"""
        if hasattr(self, '_active_streams') and request_id in self._active_streams:
            task = self._active_streams.pop(request_id)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            self._publish('llm', 'error', {'requestId': request_id, 'message': 'Aborted by user', 'code': 'aborted'})
            logger.info(f"[LLMService] Aborted: requestId={request_id}")
            return {'success': True}
        return {'success': False, 'error': 'Stream not found'}

    async def _execute_streaming(
        self,
        request_id: str,
        session_id: str,
        messages: List[Dict[str, str]],
        model: Dict[str, Any],
        mode: str,
        tools: Optional[List[str]],
        output_schema: Optional[Dict[str, Any]],
        template_id: Optional[str] = None,
        extra_meta: Optional[Dict[str, Any]] = None,
    ):
        """后台协程: 执行流式 LLM 调用 + Tools Calling loop"""
        _start_time = time.monotonic()
        _latency_ms = 0
        _status = 'success'
        _error_msg = None
        _tool_calls_recorded = []
        _token_data = {}
        try:
            model_id = model.get('id') if isinstance(model, dict) else None
            if model_id:
                self._check_usage_limits(model_id)
        except Exception as e:
            _status = 'error'
            _error_msg = str(e)
            _latency_ms = int((time.monotonic() - _start_time) * 1000)
            logger.error(f"[LLMService] Usage limit exceeded: requestId={request_id}, error={e}")
            self._publish('llm', 'error', {
                'requestId': request_id,
                'message': str(e),
                'code': 'usage_limit_exceeded',
            })
            return
        try:
            full_content = ""
            chunk_queue: queue.Queue = queue.Queue()
            loop = asyncio.get_event_loop()
            provider = model.get('provider', 'ollama')
            model_name = model.get('model', 'unknown')

            # ===== Tools Calling 循环 (max 5 rounds) =====
            max_tool_rounds = 5 if mode == 'tools' else 0
            tool_round = 0

            while tool_round <= max_tool_rounds:
                # 启动 HTTP streaming 线程
                thread_token_data = {}

                def _http_stream():
                    nonlocal thread_token_data
                    if provider == 'ollama':
                        thread_token_data = _sync_stream_ollama(model, messages, chunk_queue, tools, mode)
                    else:
                        thread_token_data = _sync_stream_openai(model, messages, chunk_queue, tools, mode)

                thread = threading.Thread(target=_http_stream, daemon=True)
                thread.start()

                # 从队列读取 chunks，批处理后 PUB
                batch_text = ""
                batch_idx = 0
                last_pub = time.monotonic()
                tool_calls_raw = []  # 累积 tool_call JSON 片段

                while True:
                    try:
                        item = await loop.run_in_executor(None, chunk_queue.get, True, 0.15)
                    except queue.Empty:
                        item = None

                    if item is None:
                        # 超时 — 检查是否需要 publish batch
                        if batch_text:
                            self._publish('llm', 'chunk', {
                                'requestId': request_id,
                                'index': batch_idx,
                                'text': batch_text,
                            })
                            batch_idx += 1
                            batch_text = ""
                        continue

                    if isinstance(item, dict) and item.get('type') == 'done':
                        # 流结束 — publish 剩余 batch
                        if batch_text:
                            self._publish('llm', 'chunk', {
                                'requestId': request_id,
                                'index': batch_idx,
                                'text': batch_text,
                            })
                        full_content = item.get('content', '')
                        _token_data = thread_token_data  # capture token info from stream thread
                        break

                    if isinstance(item, dict) and item.get('type') == 'error':
                        raise RuntimeError(item.get('message', 'Unknown streaming error'))

                    if isinstance(item, dict) and item.get('type') == 'tool_calls':
                        tool_calls_raw.append(item.get('data', ''))

                    # 文本 chunk
                    if isinstance(item, str):
                        full_content += item
                        batch_text += item

                    now = time.monotonic()
                    if batch_text and (now - last_pub >= 0.1 or len(batch_text) >= 200):
                        self._publish('llm', 'chunk', {
                            'requestId': request_id,
                            'index': batch_idx,
                            'text': batch_text,
                        })
                        batch_idx += 1
                        batch_text = ""
                        last_pub = now

                thread.join(timeout=5)

                # ===== Tools Calling 检测 =====
                if tool_round < max_tool_rounds and tool_calls_raw:
                    tool_calls = self._parse_tool_calls(tool_calls_raw)
                    if tool_calls:
                        from tools_executor import ToolExecutor
                        executor = ToolExecutor(self.multi_db)
                        for tc in tool_calls:
                            tool_name = tc.get('name', '')
                            tool_args = tc.get('arguments', {})
                            _tool_calls_recorded.append({'name': tool_name, 'arguments': tool_args})
                            self._publish('llm', 'tool_call', {
                                'requestId': request_id,
                                'toolName': tool_name,
                                'args': tool_args,
                            })
                            result = executor.execute(tool_name, tool_args)
                            self._publish('llm', 'tool_result', {
                                'requestId': request_id,
                                'toolName': tool_name,
                                'result': result,
                            })
                            # 构造 tool message 追加到 messages
                            messages.append({
                                'role': 'assistant',
                                'content': None,
                                'tool_calls': [{
                                    'id': f"call_{_make_id()}",
                                    'type': 'function',
                                    'function': {'name': tool_name, 'arguments': json.dumps(tool_args, ensure_ascii=False)},
                                }]
                            })
                            messages.append({
                                'role': 'tool',
                                'tool_call_id': f"call_{_make_id()}",
                                'content': json.dumps(result, ensure_ascii=False, default=str),
                            })
                        tool_round += 1
                        full_content = ""  # reset for next round
                        chunk_queue = queue.Queue()
                        continue  # 继续下一轮

                break  # 无 tool_calls 或达到最大轮数

            # ===== 结构化输出校验 (mode='structured') =====
            if mode == 'structured' and output_schema and full_content:
                validated = self._validate_structured_output(full_content, output_schema)
                if validated.get('success'):
                    self._publish('llm', 'done', {
                        'requestId': request_id,
                        'content': json.dumps(validated['data'], ensure_ascii=False),
                        'structured': validated['data'],
                    })
                else:
                    # 重试 (max 2)
                    retry_content = full_content
                    for attempt in range(2):
                        logger.warning(f"[LLMService] Structured validation failed, retry {attempt + 1}/2")
                        messages.append({
                            'role': 'user',
                            'content': (
                                f"Your previous response was not valid JSON matching the required schema.\n"
                                f"Error: {validated.get('error')}\n"
                                f"Schema: {json.dumps(output_schema, ensure_ascii=False)}\n"
                                f"Please output ONLY valid JSON."
                            )
                        })
                        # 重新 stream
                        retry_content = await self._sync_call_for_retry(model, messages, mode, tools, output_schema)
                        validated = self._validate_structured_output(retry_content, output_schema)
                        if validated.get('success'):
                            break

                    if validated.get('success'):
                        self._publish('llm', 'done', {
                            'requestId': request_id,
                            'content': json.dumps(validated['data'], ensure_ascii=False),
                            'structured': validated['data'],
                        })
                        full_content = retry_content
                    else:
                        self._publish('llm', 'done', {
                            'requestId': request_id,
                            'content': full_content,
                            'structured': {
                                'raw': full_content,
                                'validationError': validated.get('error', ''),
                                'retries': 2,
                                'success': False,
                            },
                        })
            else:
                self._publish('llm', 'done', {
                    'requestId': request_id,
                    'content': full_content or '',
                })

            # ===== 计算延迟 =====
            _latency_ms = int((time.monotonic() - _start_time) * 1000)

            # ===== 保存消息到 SQLite =====
            self._save_stream_messages(
                session_id, messages, full_content, model, mode, request_id,
                template_id=template_id,
                extra_meta=extra_meta,
                tool_calls_recorded=_tool_calls_recorded,
                latency_ms=_latency_ms,
                token_data=_token_data,
            )

            # ===== 记录报告交互日志 =====
            try:
                log_meta = dict(extra_meta or {})
                log_meta.setdefault('template_id', template_id)
                self._save_interaction_log(session_id, request_id, model, mode, _status, _latency_ms, log_meta)
            except Exception:
                pass

        except asyncio.CancelledError:
            _status = 'aborted'
            _latency_ms = int((time.monotonic() - _start_time) * 1000)
            self._save_stream_messages(
                session_id, messages, "", model, mode, request_id,
                template_id=template_id, extra_meta=extra_meta, latency_ms=_latency_ms, status='aborted',
                error_message='Aborted by user',
            )
            logger.info(f"[LLMService] Stream cancelled: requestId={request_id}")
            raise
        except Exception as e:
            _status = 'error'
            _error_msg = str(e)
            _latency_ms = int((time.monotonic() - _start_time) * 1000)
            logger.error(f"[LLMService] Stream error: requestId={request_id}, error={e}")
            self._publish('llm', 'error', {
                'requestId': request_id,
                'message': str(e),
                'code': 'stream_error',
            })
            self._save_stream_messages(
                session_id, messages, "", model, mode, request_id,
                template_id=template_id, extra_meta=extra_meta, latency_ms=_latency_ms, status='error',
                error_message=_error_msg,
            )
        finally:
            if hasattr(self, '_active_streams') and request_id in self._active_streams:
                self._active_streams.pop(request_id, None)

    def _publish(self, topic: str, event_type: str, data: dict):
        """线程安全的 ZMQ PUB 包装"""
        if hasattr(self, '_server') and self._server:
            self._server.publish(topic, event_type, data)

    def _parse_tool_calls(self, raw_parts: List[str]) -> List[Dict[str, Any]]:
        """解析累积的 tool_call JSON 片段"""
        try:
            raw = ''.join(raw_parts)
            # 尝试解析为 JSON 数组或单个对象
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [{'name': tc.get('function', {}).get('name', ''),
                         'arguments': json.loads(tc.get('function', {}).get('arguments', '{}'))}
                        for tc in parsed]
            elif isinstance(parsed, dict):
                func = parsed.get('function', {})
                return [{'name': func.get('name', ''),
                         'arguments': json.loads(func.get('arguments', '{}'))}]
        except (json.JSONDecodeError, AttributeError):
            pass
        return []

    def _validate_structured_output(
        self,
        content: str,
        schema: Dict[str, Any],
    ) -> Dict[str, Any]:
        """校验结构化输出是否符合 JSON Schema

        Returns:
            {'success': True, 'data': {...}} 或 {'success': False, 'error': '...'}
        """
        # 提取 JSON（可能被 markdown 代码块包裹）
        json_str = content.strip()
        # 尝试从 ```json ... ``` 中提取
        if json_str.startswith('```'):
            lines = json_str.split('\n')
            # 移除首尾的 ``` 行
            if len(lines) > 2:
                json_str = '\n'.join(lines[1:-1])

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            return {'success': False, 'error': f'JSON parse error: {e}', 'raw': content}

        # 简单 schema 校验（仅 required + type）
        if isinstance(schema, dict) and schema.get('type') == 'object':
            if not isinstance(data, dict):
                return {'success': False, 'error': 'Root must be object', 'raw': content}
            # 检查 required
            for req in schema.get('required', []):
                if req not in data:
                    return {'success': False, 'error': f"Missing required field: '{req}'", 'raw': content}
            # 检查 enum
            for prop_name, prop_schema in schema.get('properties', {}).items():
                if prop_name in data and 'enum' in prop_schema:
                    if data[prop_name] not in prop_schema['enum']:
                        return {
                            'success': False,
                            'error': f"'{prop_name}' must be one of {prop_schema['enum']}, got '{data[prop_name]}'",
                            'raw': content,
                        }

        return {'success': True, 'data': data}

    async def sync_chat(
        self,
        messages: List[Dict[str, str]],
        model_id: str,
    ) -> str:
        """同步非流式调用 LLM，直接返回文本内容"""
        model = _get_model_by_id(self.multi_db, model_id)
        if not model:
            raise ValueError(f"Model not found: {model_id}")
        self._check_usage_limits(model_id)
        content = await self._sync_call_for_retry(model, messages, 'chat', None, None)
        # 记录用量统计
        try:
            if model.get('id'):
                # sync_chat 拿不到 token 数据，按字符估算
                prompt_chars = sum(len(m.get('content', '')) for m in messages if m.get('content'))
                completion_chars = len(content or '')
                token_data = {
                    'prompt_tokens': max(1, int(prompt_chars / 3.5)),
                    'completion_tokens': max(1, int(completion_chars / 3.5)),
                    'total_tokens': max(1, int((prompt_chars + completion_chars) / 3.5)),
                }
                self._record_usage(model['id'], token_data)
        except Exception as e:
            logger.warning(f"[LLMService] Failed to record usage: {e}")
        return content

    async def _sync_call_for_retry(
        self,
        model: Dict[str, Any],
        messages: List[Dict[str, str]],
        mode: str,
        tools: Optional[List[str]],
        output_schema: Optional[Dict[str, Any]],
    ) -> str:
        """结构化输出重试: 同步调用 LLM (非流式)"""
        from tools_executor import get_tool_definitions

        provider = model.get('provider', 'ollama')
        if provider == 'ollama':
            payload = {
                'model': model['model'],
                'messages': messages,
                'stream': False,
                'options': {},
            }
            if model.get('temperature') is not None:
                payload['options']['temperature'] = model['temperature']
            resp = await asyncio.to_thread(
                lambda: requests.post(
                    f"{model['url'].rstrip('/')}/api/chat",
                    json=payload,
                    timeout=model.get('timeout', 300),
                )
            )
            data = resp.json()
            return data.get('message', {}).get('content', '')
        else:
            payload = {
                'model': model['model'],
                'messages': messages,
                'stream': False,
            }
            if model.get('temperature') is not None:
                payload['temperature'] = model['temperature']
            headers = {'Content-Type': 'application/json'}
            if model.get('api_key'):
                headers['Authorization'] = f"Bearer {model['api_key']}"
            chat_base = model['url'].rstrip('/')
            if chat_base.endswith('/v1'):
                chat_base = chat_base[:-3]
            resp = await asyncio.to_thread(
                lambda: requests.post(
                    f"{chat_base}/v1/chat/completions",
                    json=payload, headers=headers,
                    timeout=model.get('timeout', 300),
                )
            )
            data = resp.json()
            return data.get('choices', [{}])[0].get('message', {}).get('content', '')

    # 分析报告重跑/重新生成等操作不写入会话记录
    _ANALYSIS_SESSION_PREFIXES = ('comm-', 'regen-', 'pipeline-', 'ai-')

    def _save_stream_messages(
        self,
        session_id: str,
        messages: List[Dict[str, str]],
        full_content: str,
        model: Dict[str, Any],
        mode: str,
        request_id: str,
        template_id: Optional[str] = None,
        extra_meta: Optional[Dict[str, Any]] = None,
        tool_calls_recorded: Optional[List[Dict[str, Any]]] = None,
        latency_ms: int = 0,
        status: str = 'success',
        error_message: Optional[str] = None,
        token_data: Optional[Dict[str, Any]] = None,
    ):
        """保存流式完成后的消息到 SQLite（完整日志）"""
        # 先记录用量统计（所有会话类型都记录，包括分析报告）
        try:
            model_obj = model if isinstance(model, dict) else None
            if model_obj and model_obj.get('id') and status in ('success', 'error'):
                self._record_usage(model_obj.get('id'), token_data or {})
        except Exception as e:
            logger.warning(f"[LLMService] Failed to record usage: {e}")

        try:
            # AI 助手和分析报告会话：跳过消息持久化
            if any(session_id.startswith(p) for p in self._ANALYSIS_SESSION_PREFIXES):
                logger.debug(f"[LLMService] Skip persistence for session: {session_id}")
                return

            # 确保 session 存在（内联 session 自动创建）
            sessions_db = self.multi_db.sessions_db
            existing = sessions_db.fetchone(
                "SELECT id FROM llm_sessions WHERE id=?", (session_id,)
            )
            if not existing:
                module_type = 'project_analysis' if session_id.startswith('_inline_') else 'ai_assistant'
                now = datetime.now().isoformat()
                sessions_db.execute(
                    """INSERT INTO llm_sessions (id, module_type, title, status, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (session_id, module_type, f'Inline Chat {session_id[-8:]}', 'active', now, now),
                )
                sessions_db.commit()
                logger.debug(f"[LLMService] Auto-created session: {session_id}")

            # 保存 assistant 消息
            if full_content:
                self.add_message(session_id, 'assistant', full_content)
                logger.debug(f"[LLMService] Messages saved for session={session_id}")

            # 记录调用日志
            self._save_call_log(self.multi_db.main_db, session_id, messages,
                                full_content, model, request_id, template_id,
                                extra_meta, tool_calls_recorded, latency_ms,
                                status, error_message, token_data)
        except Exception as e:
            logger.error(f"[LLMService] Failed to save messages: {e}")

    def _save_call_log(self, main_db, session_id, messages, full_content, model,
                       request_id, template_id, extra_meta, tool_calls_recorded,
                       latency_ms, status, error_message, token_data):
        """记录 LLM 调用日志（llm_call_logs）"""
        try:
            log_id = _make_id()
            now = datetime.now().isoformat()
            messages_json = json.dumps([
                {k: v for k, v in m.items() if k in ('role', 'content')}
                for m in messages
            ], ensure_ascii=False, default=str)
            response_content = full_content[:100000] if full_content else None
            tool_calls_json = json.dumps(tool_calls_recorded or [], ensure_ascii=False, default=str)
            token_data = token_data or {}
            # 当 API 未返回 token 用量时，按字符数估算
            if not token_data.get('total_tokens'):
                prompt_chars = sum(len(m.get('content', '')) for m in messages if m.get('content'))
                completion_chars = len(full_content or '')
                estimated_prompt = max(1, int(prompt_chars / 3.5))
                estimated_completion = max(1, int(completion_chars / 3.5))
                token_data['prompt_tokens'] = token_data.get('prompt_tokens') or estimated_prompt
                token_data['completion_tokens'] = token_data.get('completion_tokens') or estimated_completion
                token_data['total_tokens'] = token_data.get('total_tokens') or (estimated_prompt + estimated_completion)
            main_db.execute(
                """INSERT INTO llm_call_logs
                   (id, session_id, request_id, model_id, provider, model_name, mode,
                    template_id, messages_json, response_content, tool_calls_json,
                    token_prompt, token_completion, token_total,
                    latency_ms, status, error_message, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (log_id, session_id, request_id, model.get('id'), model.get('provider'),
                 model.get('model'), mode,
                 template_id, messages_json, response_content, tool_calls_json,
                 token_data.get('prompt_tokens'), token_data.get('completion_tokens'),
                 token_data.get('total_tokens'),
                 latency_ms, status, error_message, now),
            )
            main_db.commit()
        except Exception as e:
            logger.error(f"[LLMService] Failed to save call log: {e}")

        # 记录每日用量（仅成功/错误的实际调用，且 model_id 有效）
        try:
            model_id = model.get('id') if isinstance(model, dict) else None
            if model_id and status in ('success', 'error'):
                self._record_usage(model_id, token_data or {})
        except Exception as e:
            logger.warning(f"[LLMService] Failed to record usage: {e}")

    def _check_usage_limits(self, model_id: str):
        """检查模型每日用量是否超限，超限则抛出 UsageLimitExceeded"""
        if not model_id:
            return
        main_db = self.multi_db.main_db
        self._ensure_usage_table()
        limits = main_db.fetchone(
            "SELECT max_requests_per_day, max_tokens_per_day FROM model_configs WHERE id = ?",
            (model_id,)
        )
        if not limits:
            return
        max_req = limits.get('max_requests_per_day', 0) or 0
        max_tok = limits.get('max_tokens_per_day', 0) or 0
        if max_req == 0 and max_tok == 0:
            return
        today = datetime.now().strftime('%Y-%m-%d')
        usage = main_db.fetchone(
            "SELECT request_count, total_tokens FROM model_daily_usage WHERE model_id = ? AND date = ?",
            (model_id, today)
        )
        req_count = usage['request_count'] if usage else 0
        tok_count = usage['total_tokens'] if usage else 0
        if max_req > 0 and req_count >= max_req:
            raise Exception(f"UsageLimitExceeded: Daily request limit reached ({req_count}/{max_req})")
        if max_tok > 0 and tok_count >= max_tok:
            raise Exception(f"UsageLimitExceeded: Daily token limit reached ({tok_count}/{max_tok})")

    def _ensure_usage_table(self):
        try:
            main_db = self.multi_db.main_db
            main_db.execute("SELECT 1 FROM model_daily_usage LIMIT 1")
        except Exception:
            main_db.execute("""CREATE TABLE IF NOT EXISTS model_daily_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                model_id TEXT NOT NULL REFERENCES model_configs(id) ON DELETE CASCADE,
                date TEXT NOT NULL,
                request_count INTEGER DEFAULT 0,
                prompt_tokens INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                UNIQUE(model_id, date)
            )""")
            main_db.execute("CREATE INDEX IF NOT EXISTS idx_mdu_model ON model_daily_usage(model_id)")
            main_db.execute("CREATE INDEX IF NOT EXISTS idx_mdu_date ON model_daily_usage(date)")

    def _record_usage(self, model_id: str, token_data: dict):
        """记录模型每日用量（INSERT OR REPLACE 累加）"""
        if not model_id:
            return
        main_db = self.multi_db.main_db
        self._ensure_usage_table()
        today = datetime.now().strftime('%Y-%m-%d')
        prompt = token_data.get('prompt_tokens') or 0
        completion = token_data.get('completion_tokens') or 0
        total = token_data.get('total_tokens') or 0
        main_db.execute(
            """INSERT INTO model_daily_usage (model_id, date, request_count, prompt_tokens, completion_tokens, total_tokens, created_at, updated_at)
               VALUES (?, ?, 1, ?, ?, ?, datetime('now'), datetime('now'))
               ON CONFLICT(model_id, date) DO UPDATE SET
                 request_count = request_count + 1,
                 prompt_tokens = prompt_tokens + ?,
                 completion_tokens = completion_tokens + ?,
                 total_tokens = total_tokens + ?,
                 updated_at = datetime('now')""",
            (model_id, today, prompt, completion, total, prompt, completion, total)
        )

    def _save_interaction_log(
        self,
        session_id: str,
        request_id: str,
        model: Dict[str, Any],
        mode: str,
        status: str,
        latency_ms: int,
        meta: Dict[str, Any],
    ):
        """记录报告/分析交互事件到 report_interaction_log"""
        try:
            main_db = self.multi_db.main_db
            now = datetime.now().isoformat()
            log_id = _make_id()
            main_db.execute(
                """INSERT INTO report_interaction_log
                   (id, session_id, request_id, provider, model_name, mode, status,
                    latency_ms, meta_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (log_id, session_id, request_id,
                 model.get('provider'), model.get('model'), mode, status,
                 latency_ms, json.dumps(meta, ensure_ascii=False, default=str), now),
            )
            main_db.commit()
        except Exception as e:
            logger.error(f"[LLMService] Failed to save interaction log: {e}")


# ==================== HTTP Streaming 实现 ====================

def _sync_stream_ollama(
    model_config: Dict[str, Any],
    messages: List[Dict[str, str]],
    chunk_queue,
    tools: Optional[List[str]] = None,
    mode: str = 'chat',
) -> Dict[str, Any]:
    """在独立线程中运行: Ollama streaming HTTP
    Returns: token info dict {prompt_tokens, completion_tokens, total_tokens}
    """
    import json as _json
    base_url = model_config['url'].rstrip('/')
    if base_url.endswith('/v1'):
        base_url = base_url[:-3]
    payload = {
        'model': model_config['model'],
        'messages': messages,
        'stream': True,
        'options': {},
    }
    if model_config.get('temperature') is not None:
        payload['options']['temperature'] = model_config['temperature']
    if model_config.get('max_tokens') is not None:
        payload['options']['num_predict'] = model_config['max_tokens']

    token_info = {}
    timeout = model_config.get('timeout', 300)

    # 日志：提交给模型的最终请求
    _log_payload = {
        'provider': 'ollama',
        'url': base_url + '/api/chat',
        'model': payload['model'],
        'mode': mode,
        'temperature': payload.get('options', {}).get('temperature'),
        'num_predict': payload.get('options', {}).get('num_predict'),
        'messages': [
            {'role': m.get('role', ''), 'content_len': len(m.get('content', '')), 'content_preview': m.get('content', '')[:3000]}
            for m in payload.get('messages', [])
        ],
    }
    logger.info(f"[LLM_REQ] Ollama 请求: {json.dumps(_log_payload, ensure_ascii=False)}")

    try:
        resp = requests.post(f'{base_url}/api/chat', json=payload, stream=True, timeout=timeout)
        if resp.status_code != 200:
            chunk_queue.put({'type': 'error', 'message': f'Ollama API error {resp.status_code}'})
            return token_info

        full_content = ""
        for line_bytes in resp.iter_lines():
            if not line_bytes:
                continue
            line = line_bytes.decode('utf-8')
            try:
                data = _json.loads(line)
                if data.get('done'):
                    eval_count = data.get('eval_count')
                    prompt_eval_count = data.get('prompt_eval_count')
                    if eval_count is not None or prompt_eval_count is not None:
                        token_info = {
                            'prompt_tokens': prompt_eval_count,
                            'completion_tokens': eval_count,
                            'total_tokens': (prompt_eval_count or 0) + (eval_count or 0),
                        }
                    chunk_queue.put({'type': 'done', 'content': full_content})
                    break
                chunk = data.get('message', {}).get('content', '')
                if chunk:
                    full_content += chunk
                    chunk_queue.put(chunk)
            except _json.JSONDecodeError:
                continue
    except Exception as e:
        chunk_queue.put({'type': 'error', 'message': str(e)})
    finally:
        chunk_queue.put({'type': 'done', 'content': ''})  # sentinel for error case
    return token_info


def _sync_stream_openai(
    model_config: Dict[str, Any],
    messages: List[Dict[str, str]],
    chunk_queue,
    tools: Optional[List[str]] = None,
    mode: str = 'chat',
) -> Dict[str, Any]:
    """在独立线程中运行: OpenAI 兼容 streaming HTTP
    Returns: token info dict {prompt_tokens, completion_tokens, total_tokens}
    """
    import json as _json
    base_url = model_config['url'].rstrip('/')
    if base_url.endswith('/v1'):
        base_url = base_url[:-3]
    payload = {
        'model': model_config['model'],
        'messages': messages,
        'stream': True,
    }
    if model_config.get('temperature') is not None:
        payload['temperature'] = model_config['temperature']
    if model_config.get('max_tokens') is not None:
        payload['max_tokens'] = model_config['max_tokens']

    # Tools Calling 支持
    if mode == 'tools' and tools:
        from tools_executor import get_tool_definitions
        tool_defs = get_tool_definitions(tools)
        if tool_defs:
            payload['tools'] = tool_defs
            payload['tool_choice'] = 'auto'

    headers = {'Content-Type': 'application/json'}
    api_key = model_config.get('api_key', '')
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'

    token_info = {}
    timeout = model_config.get('timeout', 300)

    # 日志：提交给模型的最终请求
    _log_payload = {
        'provider': 'openai',
        'url': base_url + '/v1/chat/completions',
        'model': payload['model'],
        'mode': mode,
        'temperature': payload.get('temperature'),
        'max_tokens': payload.get('max_tokens'),
        'tools': list(payload.get('tools', [])) if payload.get('tools') else None,
        'messages': [
            {'role': m.get('role', ''), 'content_len': len(m.get('content', '')), 'content_preview': m.get('content', '')[:3000]}
            for m in payload.get('messages', [])
        ],
    }
    logger.info(f"[LLM_REQ] OpenAI 请求: {json.dumps(_log_payload, ensure_ascii=False)}")

    try:
        resp = requests.post(
            f'{base_url}/v1/chat/completions',
            json=payload, headers=headers, stream=True, timeout=timeout
        )
        if resp.status_code != 200:
            chunk_queue.put({'type': 'error', 'message': f'OpenAI API error {resp.status_code}: {resp.text[:200]}'})
            return token_info

        full_content = ""
        tool_calls_parts = []
        usage_data = {}

        for line_bytes in resp.iter_lines():
            if not line_bytes:
                continue
            line = line_bytes.decode('utf-8')
            if not line.startswith('data: '):
                continue
            data_str = line[6:].strip()
            if data_str == '[DONE]':
                if tool_calls_parts:
                    chunk_queue.put({'type': 'tool_calls', 'data': ''.join(tool_calls_parts)})
                chunk_queue.put({'type': 'done', 'content': full_content})
                break
            try:
                data = _json.loads(data_str)
                delta = data.get('choices', [{}])[0].get('delta', {})

                # 捕获 token 使用量（OpenAI 在最后一条非 DONE 消息中返回 usage）
                if data.get('usage'):
                    usage_data = data['usage']

                # 文本内容
                chunk = delta.get('content', '')
                if chunk:
                    full_content += chunk
                    chunk_queue.put(chunk)

                # 工具调用
                tc = delta.get('tool_calls')
                if tc:
                    tool_calls_parts.append(_json.dumps(tc))
            except _json.JSONDecodeError:
                continue

        # 解析 token 使用量
        if usage_data:
            token_info = {
                'prompt_tokens': usage_data.get('prompt_tokens'),
                'completion_tokens': usage_data.get('completion_tokens'),
                'total_tokens': usage_data.get('total_tokens'),
            }
    except Exception as e:
        chunk_queue.put({'type': 'error', 'message': str(e)})
    finally:
        chunk_queue.put({'type': 'done', 'content': ''})  # sentinel
    return token_info

def register_llm_methods(server: ZMQServer, multi_db: MultiDBManager):
    """注册 LLM 相关方法到 ZMQServer"""

    service = LLMService(multi_db)
    service._server = server  # 用于 ZMQ PUB 推送

    from prompt_manager import PromptManager
    pm = PromptManager(multi_db)

    # ==================== Session 管理 (v2) ====================

    @server.register('session.list')
    def list_sessions(
        module_type: Optional[str] = None,
        project_id: Optional[str] = None,
        moduleType: Optional[str] = None,
        projectId: Optional[str] = None,
        status: str = 'active',
    ):
        return {'sessions': service.list_sessions(
            module_type or moduleType, project_id or projectId, status
        )}

    @server.register('session.create')
    def create_session(
        module_type: str = None,
        title: str = '',
        project_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        moduleType: str = None,
        projectId: Optional[str] = None,
    ):
        return service.create_session(
            module_type or moduleType, title, project_id or projectId, metadata
        )

    @server.register('session.delete')
    def delete_session(session_id: str = None, sessionId: str = None):
        return service.delete_session(session_id or sessionId)

    @server.register('session.clearAll')
    def clear_all_sessions():
        return service.clear_all_sessions()

    @server.register('session.getMessages')
    def get_messages(
        session_id: str = None,
        sessionId: str = None,
        limit: int = 100,
        offset: int = 0,
    ):
        return {'messages': service.get_messages(
            session_id or sessionId, limit, offset
        )}

    @server.register('session.addMessage')
    def add_message(
        session_id: str = None,
        sessionId: str = None,
        role: str = '',
        content: str = '',
        token_count: Optional[int] = None,
        tokenCount: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        return service.add_message(
            session_id or sessionId, role, content, token_count or tokenCount, metadata
        )

    @server.register('session.deleteMessage')
    def delete_message(message_id: str = None, messageId: str = None):
        return service.delete_message(message_id or messageId)

    @server.register('session.updateMeta')
    def update_meta(
        session_id: str = None,
        sessionId: str = None,
        metadata: Dict[str, Any] = None,
    ):
        return service.update_metadata(session_id or sessionId, metadata)

    # ==================== LLM 推理 (v2) ====================

    @server.register('llm.chat')
    async def chat(
        session_id: str = None,
        model_id: str = None,
        sessionId: str = None,
        modelId: str = None,
        mode: str = 'chat',
        messages: Optional[List[Dict[str, str]]] = None,
        template_id: Optional[str] = None,
        templateId: Optional[str] = None,
        variables: Optional[Dict[str, Any]] = None,
        tools: Optional[List[str]] = None,
        output_schema: Optional[Dict[str, Any]] = None,
        outputSchema: Optional[Dict[str, Any]] = None,
    ):
        """统一流式对话入口"""
        from zmq_server import current_call_id
        _cid = current_call_id.get()
        if _cid:
            logger.info(f"[{_cid}] llm.chat mode={mode} template={template_id or templateId}")

        session_id = session_id or sessionId
        model_id = model_id or modelId
        template_id = template_id or templateId
        output_schema = output_schema or outputSchema

        if not session_id:
            raise ValueError("sessionId is required")
        if template_id:
            rendered = pm.render(template_id, variables or {})
            messages = rendered['messages']
            if rendered.get('mode') and mode == 'chat':
                mode = rendered['mode']
            if rendered.get('tools') and not tools:
                tools = rendered['tools']
            if rendered.get('outputSchema') and not output_schema:
                output_schema = rendered['outputSchema']

        if not messages:
            raise ValueError("Either 'messages' or 'templateId' + 'variables' is required")

        extra_meta = {}
        if template_id:
            extra_meta['template_id'] = template_id
        if variables:
            for k in ('pipeline_step', 'community_id', 'community_level', 'batch_id', 'source'):
                if k in variables:
                    extra_meta[k] = variables[k]

        return await service.streaming_chat(
            session_id, messages, model_id, mode, tools, output_schema,
            template_id=template_id, extra_meta=extra_meta,
        )

    @server.register('llm.abortChat')
    async def abort_chat(request_id: str):
        """中止流式调用"""
        return await service.abort_chat(request_id)

    # ==================== 分析报告会话管理 (analysisSession) ====================

    @server.register('analysisSession.list')
    def list_analysis_sessions(
        project_id: str = None,
        task_id: str = None,
        report_id: str = None,
        projectId: str = None,
        taskId: str = None,
        reportId: str = None,
    ):
        """按项目/任务/报告查询分析会话"""
        pid = project_id or projectId
        tid = task_id or taskId
        rid = report_id or reportId
        main_db = multi_db.main_db
        sql = "SELECT * FROM analysis_sessions WHERE 1=1"
        params = []
        if pid:
            sql += " AND project_id = ?"
            params.append(pid)
        if tid:
            sql += " AND task_id = ?"
            params.append(tid)
        if rid:
            sql += " AND report_id = ?"
            params.append(rid)
        sql += " ORDER BY created_at DESC"
        return {'sessions': main_db.fetchall(sql, tuple(params))}

    @server.register('analysisSession.create')
    def create_analysis_session(
        project_id: str,
        task_id: str,
        session_id: str,
        report_id: str = None,
        metadata: Dict[str, Any] = None,
        projectId: str = None,
        taskId: str = None,
        sessionId: str = None,
        reportId: str = None,
    ):
        """创建分析会话关联记录"""
        pid = project_id or projectId
        tid = task_id or taskId
        sid = session_id or sessionId
        rid = report_id or reportId
        import uuid, json
        aid = f"anas-{uuid.uuid4().hex[:8]}"
        now = datetime.now().isoformat()
        main_db = multi_db.main_db
        main_db.execute(
            """INSERT INTO analysis_sessions (id, project_id, task_id, report_id, session_id, metadata, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (aid, pid, tid, rid, sid, json.dumps(metadata or {}), now, now),
        )
        main_db.conn.commit()
        return {'id': aid, 'sessionId': sid}

    @server.register('analysisSession.delete')
    def delete_analysis_session(
        id: str = None,
        session_id: str = None,
        sessionId: str = None,
    ):
        """删除分析会话关联"""
        main_db = multi_db.main_db
        sid = session_id or sessionId
        if id:
            main_db.execute("DELETE FROM analysis_sessions WHERE id = ?", (id,))
        elif sid:
            main_db.execute("DELETE FROM analysis_sessions WHERE session_id = ?", (sid,))
        else:
            raise ValueError("Either 'id' or 'sessionId' is required")
        main_db.conn.commit()
        return {'success': True}

    # ==================== Prompt 模板管理 (统一实例) ====================

    @server.register('promptTemplate.list')
    def list_templates(
        mode: Optional[str] = None,
        module_type: Optional[str] = None,
        category: Optional[str] = None,
        locale: Optional[str] = None,
        moduleType: Optional[str] = None,
    ):
        mt = module_type or moduleType
        return {'templates': pm.list_templates(mode, mt, category, locale)}

    @server.register('promptTemplate.get')
    def get_template(template_id: str, locale: Optional[str] = None):
        return pm.get_template(template_id, locale)

    @server.register('promptTemplate.create')
    def create_template(
        name: str,
        mode: str,
        module_type: Optional[str] = None,
        category: str = 'general',
        locale: str = 'zh-CN',
        system_prompt: Optional[str] = None,
        user_prompt_template: Optional[str] = None,
        tools_json: Optional[str] = None,
        tool_strategy: str = 'auto',
        output_schema_json: Optional[str] = None,
        output_example: Optional[str] = None,
        variables_json: Optional[str] = None,
    ):
        return pm.create_template(
            name, mode, module_type, category, locale,
            system_prompt, user_prompt_template,
            tools_json, tool_strategy,
            output_schema_json, output_example, variables_json,
        )

    @server.register('promptTemplate.update')
    def update_template(template_id: str, **kwargs):
        return pm.update_template(template_id, **kwargs)

    @server.register('promptTemplate.delete')
    def delete_template(template_id: str):
        return pm.delete_template(template_id)

    @server.register('promptTemplate.render')
    def render_template(template_id: str, variables: Dict[str, Any], locale: Optional[str] = None):
        return pm.render(template_id, variables, locale)

    @server.register('promptTemplate.restoreDefaults')
    def restore_defaults(locale: Optional[str] = None):
        return pm.restore_defaults(locale)

    @server.register('promptTemplate.getDefaultLocale')
    def get_default_locale():
        return {'locale': pm.get_default_locale()}

    @server.register('promptTemplate.setDefaultLocale')
    def set_default_locale(locale: str):
        return pm.set_default_locale(locale)

    return server
