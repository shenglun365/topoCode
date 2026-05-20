"""LLM 后端服务 — 统一 LLM API 网关

Phase 1: session.* RPC 方法 + LLMService 类骨架
Phase 2: streaming_chat() + ZMQ PUB 推送
Phase 3: 三模式路由 + Prompt 模板 + Tools Calling
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

def _get_default_model(multi_db: MultiDBManager) -> Optional[Dict[str, Any]]:
    """获取默认模型配置"""
    return multi_db.main_db.fetchone("SELECT * FROM model_configs WHERE is_default = 1")


def _get_model_by_id(multi_db: MultiDBManager, model_id: str) -> Optional[Dict[str, Any]]:
    """按 ID 获取模型配置"""
    return multi_db.main_db.fetchone("SELECT * FROM model_configs WHERE id = ?", (model_id,))


# ==================== LLM API 调用 (v1 — 后续 Phase 2 重构为 streaming) ====================

def _sync_call_ollama_chat(
    model_config: Dict[str, Any],
    messages: List[Dict[str, str]],
) -> str:
    """调用 Ollama /api/chat (同步)"""
    base_url = model_config['url'].rstrip('/')
    payload = {
        'model': model_config['model'],
        'messages': messages,
        'stream': False,
        'options': {},
    }
    if model_config.get('temperature') is not None:
        payload['options']['temperature'] = model_config['temperature']
    if model_config.get('max_tokens') is not None:
        payload['options']['num_predict'] = model_config['max_tokens']

    timeout = model_config.get('timeout', 300)  # default 300s
    resp = requests.post(f'{base_url}/api/chat', json=payload, timeout=timeout)
    if resp.status_code != 200:
        raise RuntimeError(f'Ollama API error {resp.status_code}: {resp.text[:200]}')
    data = resp.json()
    return data.get('message', {}).get('content', '')


def _sync_call_openai_chat(
    model_config: Dict[str, Any],
    messages: List[Dict[str, str]],
) -> str:
    """调用 OpenAI 兼容 /v1/chat/completions (同步)"""
    base_url = model_config['url'].rstrip('/')
    payload = {
        'model': model_config['model'],
        'messages': messages,
        'stream': False,
    }
    if model_config.get('temperature') is not None:
        payload['temperature'] = model_config['temperature']
    if model_config.get('max_tokens') is not None:
        payload['max_tokens'] = model_config['max_tokens']

    headers = {'Content-Type': 'application/json'}
    api_key = model_config.get('api_key', '')
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'

    timeout = model_config.get('timeout', 300)
    resp = requests.post(f'{base_url}/v1/chat/completions', json=payload, headers=headers, timeout=timeout)
    if resp.status_code != 200:
        raise RuntimeError(f'OpenAI API error {resp.status_code}: {resp.text[:200]}')
    data = resp.json()
    return data.get('choices', [{}])[0].get('message', {}).get('content', '')


async def _call_llm(
    model_config: Dict[str, Any],
    messages: List[Dict[str, str]],
) -> str:
    """根据 provider 路由到对应 API (通过 to_thread 避免阻塞事件循环)"""
    provider = model_config.get('provider', 'ollama')
    if provider == 'ollama':
        return await asyncio.to_thread(_sync_call_ollama_chat, model_config, messages)
    elif provider in ('openai', 'custom', 'lm-studio'):
        return await asyncio.to_thread(_sync_call_openai_chat, model_config, messages)
    else:
        raise RuntimeError(f'Unsupported provider: {provider}')


# ==================== 业务方法 (v1 保留) ====================

async def _summarize_code(
    multi_db: MultiDBManager,
    code: str,
    model_id: Optional[str] = None,
) -> Dict[str, Any]:
    """压缩长代码为伪码"""
    if not code or len(code.strip()) == 0:
        raise ValueError('Code is empty')

    if len(code) <= 500:
        return {
            'content': code,
            'originalLength': len(code),
            'summarizedLength': len(code),
            'compressed': False,
        }

    if model_id:
        model = _get_model_by_id(multi_db, model_id)
    else:
        model = _get_default_model(multi_db)
    if not model:
        raise ValueError('No LLM model configured')

    system_prompt = (
        '你是一个代码压缩助手。用户会提供一段较长的代码，请将其压缩为简洁的伪码，'
        '保留核心逻辑和关键步骤。用中文回答。只输出伪码，不要额外解释。'
    )
    user_prompt = f'请将以下代码压缩为伪码（保留核心逻辑）：\n\n```\n{code}\n```\n\n只保留核心逻辑，用简洁的中文伪码表示。'

    messages = [
        {'role': 'system', 'content': system_prompt},
        {'role': 'user', 'content': user_prompt},
    ]

    content = await _call_llm(model, messages)
    return {
        'content': content,
        'originalLength': len(code),
        'summarizedLength': len(content),
        'compressed': True,
    }


async def _explain_symbol(
    multi_db: MultiDBManager,
    symbol_name: str,
    symbol_type: str,
    code_snippet: str,
    file_name: Optional[str] = None,
    model_id: Optional[str] = None,
) -> Dict[str, Any]:
    """解释代码符号"""
    if model_id:
        model = _get_model_by_id(multi_db, model_id)
    else:
        model = _get_default_model(multi_db)
    if not model:
        raise ValueError('No LLM model configured')

    system_prompt = (
        '你是一个专业的代码分析助手。用户会提供一个代码符号（函数/类/方法/宏）及其代码片段。'
        '请用简洁的语言解释：1. 这个符号的功能和作用 2. 关键参数和返回值 3. 在项目中可能的角色。'
        '请用中文回答，保持简洁专业。'
    )

    parts = [f'## 符号信息\n- 名称: {symbol_name}\n- 类型: {symbol_type}']
    if file_name:
        parts.append(f'- 文件: {file_name}')
    parts.append(f'\n## 代码片段\n```\n{code_snippet}\n```\n\n请解释这个代码符号。')
    user_prompt = '\n'.join(parts)

    messages = [
        {'role': 'system', 'content': system_prompt},
        {'role': 'user', 'content': user_prompt},
    ]

    content = await _call_llm(model, messages)
    return {'content': content}


# ==================== Session 管理 (SQLite 持久化) ====================

def _make_id() -> str:
    return uuid.uuid4().hex[:12]


# ==================== LLMService 类骨架 ====================

class LLMService:
    """统一 LLM 服务 (Phase 1: session 管理; Phase 2-3: streaming + tools + structured)"""

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
        session_id = _make_id()
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

    # ==================== Streaming LLM (Phase 2) ====================

    async def streaming_chat(
        self,
        session_id: str,
        messages: List[Dict[str, str]],
        model_id: str,
        mode: str = 'chat',
        tools: Optional[List[str]] = None,
        output_schema: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """发起流式 LLM 请求，立即返回 requestId，chunks 通过 ZMQ PUB 推送

        Args:
            session_id: 会话 ID
            messages: 消息历史
            model_id: 模型配置 ID
            mode: chat | tools | structured
            tools: tools 模式下可用的工具名列表
            output_schema: structured 模式下的 JSON Schema
        """
        if mode not in ('chat', 'tools', 'structured'):
            raise ValueError(f"Invalid mode: {mode}")

        # 验证模型存在
        model = _get_model_by_id(self.multi_db, model_id)
        if not model:
            raise ValueError(f"Model not found: {model_id}")

        request_id = _make_id()

        # 后台启动流式任务
        task = asyncio.create_task(
            self._execute_streaming(request_id, session_id, messages, model, mode, tools, output_schema)
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
    ):
        """后台协程: 执行流式 LLM 调用 + Tools Calling loop"""
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
                def _http_stream():
                    if provider == 'ollama':
                        _sync_stream_ollama(model, messages, chunk_queue, tools, mode)
                    else:
                        _sync_stream_openai(model, messages, chunk_queue, tools, mode)

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
            elif mode != 'structured':
                self._publish('llm', 'done', {
                    'requestId': request_id,
                    'content': full_content,
                })

            # ===== 保存消息到 SQLite =====
            self._save_stream_messages(session_id, messages, full_content, model, mode, request_id)

        except asyncio.CancelledError:
            logger.info(f"[LLMService] Stream cancelled: requestId={request_id}")
            raise
        except Exception as e:
            logger.error(f"[LLMService] Stream error: requestId={request_id}, error={e}")
            self._publish('llm', 'error', {
                'requestId': request_id,
                'message': str(e),
                'code': 'stream_error',
            })
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
            resp = await asyncio.to_thread(
                lambda: requests.post(
                    f"{model['url'].rstrip('/')}/v1/chat/completions",
                    json=payload, headers=headers,
                    timeout=model.get('timeout', 300),
                )
            )
            data = resp.json()
            return data.get('choices', [{}])[0].get('message', {}).get('content', '')

    def _save_stream_messages(
        self,
        session_id: str,
        messages: List[Dict[str, str]],
        full_content: str,
        model: Dict[str, Any],
        mode: str,
        request_id: str,
    ):
        """保存流式完成后的消息到 SQLite"""
        try:
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
            self.add_message(session_id, 'assistant', full_content)
            logger.debug(f"[LLMService] Messages saved for session={session_id}")

            # 记录调用日志（llm_call_logs 在主库）
            main_db = self.multi_db.main_db
            log_id = _make_id()
            now = datetime.now().isoformat()
            main_db.execute(
                """INSERT INTO llm_call_logs
                   (id, session_id, request_id, model_id, provider, model_name, mode, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (log_id, session_id, request_id, model.get('id'), model.get('provider'),
                 model.get('model'), mode, 'success', now),
            )
            main_db.commit()
        except Exception as e:
            logger.error(f"[LLMService] Failed to save messages: {e}")

    def save_messages_batch(
        self,
        session_id: str,
        messages: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """批量保存消息（用于 llm.chat 完成后一次性持久化 user + assistant + tool）"""
        for msg in messages:
            self.add_message(
                session_id,
                msg.get('role', 'user'),
                msg.get('content', ''),
                token_count=msg.get('tokenCount'),
                metadata=msg.get('metadata'),
            )
        return {'success': True, 'count': len(messages)}


# ==================== HTTP Streaming 实现 ====================

def _sync_stream_ollama(
    model_config: Dict[str, Any],
    messages: List[Dict[str, str]],
    chunk_queue,
    tools: Optional[List[str]] = None,
    mode: str = 'chat',
):
    """在独立线程中运行: Ollama streaming HTTP"""
    import json as _json
    base_url = model_config['url'].rstrip('/')
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

    timeout = model_config.get('timeout', 300)
    try:
        resp = requests.post(f'{base_url}/api/chat', json=payload, stream=True, timeout=timeout)
        if resp.status_code != 200:
            chunk_queue.put({'type': 'error', 'message': f'Ollama API error {resp.status_code}'})
            return

        full_content = ""
        for line_bytes in resp.iter_lines():
            if not line_bytes:
                continue
            line = line_bytes.decode('utf-8')
            try:
                data = _json.loads(line)
                if data.get('done'):
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


def _sync_stream_openai(
    model_config: Dict[str, Any],
    messages: List[Dict[str, str]],
    chunk_queue,
    tools: Optional[List[str]] = None,
    mode: str = 'chat',
):
    """在独立线程中运行: OpenAI 兼容 streaming HTTP"""
    import json as _json
    base_url = model_config['url'].rstrip('/')
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

    timeout = model_config.get('timeout', 300)
    try:
        resp = requests.post(
            f'{base_url}/v1/chat/completions',
            json=payload, headers=headers, stream=True, timeout=timeout
        )
        if resp.status_code != 200:
            chunk_queue.put({'type': 'error', 'message': f'OpenAI API error {resp.status_code}: {resp.text[:200]}'})
            return

        full_content = ""
        tool_calls_parts = []

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
    except Exception as e:
        chunk_queue.put({'type': 'error', 'message': str(e)})
    finally:
        chunk_queue.put({'type': 'done', 'content': ''})  # sentinel

def register_llm_methods(server: ZMQServer, multi_db: MultiDBManager):
    """注册 LLM 相关方法到 ZMQServer"""

    service = LLMService(multi_db)
    service._server = server  # Phase 2: 用于 ZMQ PUB 推送

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
        """统一流式对话入口

        两种调用方式:
          1. 直接传 messages: {sessionId, modelId, mode, messages}
          2. 使用模板: {sessionId, modelId, templateId, variables}
             → 后端渲染模板生成 messages
        """
        # 兼容 camelCase / snake_case
        session_id = session_id or sessionId
        model_id = model_id or modelId
        template_id = template_id or templateId
        output_schema = output_schema or outputSchema

        if not session_id:
            raise ValueError("sessionId is required")
        # 模板渲染优先
        if template_id:
            from prompt_manager import PromptManager
            pm = PromptManager(multi_db)
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

        return await service.streaming_chat(session_id, messages, model_id, mode, tools, output_schema)

    @server.register('llm.abortChat')
    async def abort_chat(request_id: str):
        """中止流式调用"""
        return await service.abort_chat(request_id)

    @server.register('session.saveMessages')
    def save_messages_batch(session_id: str, messages: List[Dict[str, Any]]):
        """批量保存消息"""
        return service.save_messages_batch(session_id, messages)

    # ==================== Prompt 模板管理 ====================

    @server.register('promptTemplate.list')
    def list_templates(
        mode: Optional[str] = None,
        module_type: Optional[str] = None,
        category: Optional[str] = None,
    ):
        from prompt_manager import PromptManager
        pm = PromptManager(multi_db)
        return {'templates': pm.list_templates(mode, module_type, category)}

    @server.register('promptTemplate.get')
    def get_template(template_id: str):
        from prompt_manager import PromptManager
        pm = PromptManager(multi_db)
        return pm.get_template(template_id)

    @server.register('promptTemplate.create')
    def create_template(
        name: str,
        mode: str,
        module_type: Optional[str] = None,
        category: str = 'general',
        system_prompt: Optional[str] = None,
        user_prompt_template: Optional[str] = None,
        tools_json: Optional[str] = None,
        tool_strategy: str = 'auto',
        output_schema_json: Optional[str] = None,
        output_example: Optional[str] = None,
        variables_json: Optional[str] = None,
    ):
        from prompt_manager import PromptManager
        pm = PromptManager(multi_db)
        return pm.create_template(
            name, mode, module_type, category,
            system_prompt, user_prompt_template,
            tools_json, tool_strategy,
            output_schema_json, output_example, variables_json,
        )

    @server.register('promptTemplate.update')
    def update_template(template_id: str, **kwargs):
        from prompt_manager import PromptManager
        pm = PromptManager(multi_db)
        return pm.update_template(template_id, **kwargs)

    @server.register('promptTemplate.delete')
    def delete_template(template_id: str):
        from prompt_manager import PromptManager
        pm = PromptManager(multi_db)
        return pm.delete_template(template_id)

    @server.register('promptTemplate.render')
    def render_template(template_id: str, variables: Dict[str, Any]):
        from prompt_manager import PromptManager
        pm = PromptManager(multi_db)
        return pm.preview(template_id, variables)

    # ==================== LLM 推理 (v1 保留) ====================

    @server.register('llm.summarizeCode')
    async def summarize_code(code: str, model_id: Optional[str] = None):
        return await _summarize_code(multi_db, code, model_id)

    @server.register('llm.explainSymbol')
    async def explain_symbol(
        symbol_name: str,
        symbol_type: str,
        code_snippet: str,
        file_name: Optional[str] = None,
        model_id: Optional[str] = None,
    ):
        return await _explain_symbol(multi_db, symbol_name, symbol_type, code_snippet, file_name, model_id)

    # ==================== 旧 chat.* 方法已移除 (替换为 session.*) ====================

    return server
