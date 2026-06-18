"""Ollama LLM Provider — BaseLLMProvider 实现

Ollama 原生 API: POST /api/chat
"""

import json as _json
import logging

import requests

from providers.base import BaseLLMProvider

logger = logging.getLogger(__name__)


class OllamaProvider(BaseLLMProvider):
    """Ollama API (自定义) 聊天补全"""

    supports_tools = True

    def chat_stream(
        self,
        model_config,
        messages,
        chunk_queue,
        tools=None,
        mode='chat',
    ):
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
        if mode == 'tools' and tools:
            payload['tools'] = tools

        token_info = {}
        timeout = model_config.get('timeout', 300)

        _log_payload = {
            'provider': 'ollama',
            'url': base_url + '/api/chat',
            'model': payload['model'],
            'mode': mode,
            'temperature': payload.get('options', {}).get('temperature'),
            'num_predict': payload.get('options', {}).get('num_predict'),
            'messages': [
                {'role': m.get('role', ''), 'content_len': len(m.get('content') or ''), 'content_preview': (m.get('content') or '')[:3000]}
                for m in payload.get('messages', [])
            ],
        }
        logger.info(f"[LLM_REQ] Ollama 请求: {_json.dumps(_log_payload, ensure_ascii=False)}")

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
            chunk_queue.put({'type': 'done', 'content': ''})
        return token_info

    def chat_sync(
        self,
        model_config,
        messages,
        mode,
        tools=None,
        output_schema=None,
    ):
        payload = {
            'model': model_config['model'],
            'messages': messages,
            'stream': False,
            'options': {},
        }
        if model_config.get('temperature') is not None:
            payload['options']['temperature'] = model_config['temperature']
        if mode == 'tools' and tools:
            payload['tools'] = tools
        resp = requests.post(
            f"{model_config['url'].rstrip('/')}/api/chat",
            json=payload,
            timeout=model_config.get('timeout', 300),
        )
        data = resp.json()
        msg = data.get('message', {})
        content = msg.get('content', '')
        eval_count = data.get('eval_count')
        prompt_eval_count = data.get('prompt_eval_count')
        usage = {}
        if eval_count is not None or prompt_eval_count is not None:
            usage = {
                'prompt_tokens': prompt_eval_count,
                'completion_tokens': eval_count,
                'total_tokens': (prompt_eval_count or 0) + (eval_count or 0),
            }

        # 解析 Ollama 原生 tool_calls 格式
        raw_calls = msg.get('tool_calls', [])
        tool_calls = []
        for tc in raw_calls:
            fn = tc.get('function', {})
            name = fn.get('name', '')
            args_raw = fn.get('arguments', {})
            # Ollama 的 arguments 是 dict，OpenAI 的是 JSON string，统一转为 string
            arguments_str = _json.dumps(args_raw) if isinstance(args_raw, dict) else str(args_raw)
            tool_calls.append({
                "id": tc.get("id", ""),
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": arguments_str,
                },
            })

        return {
            'content': content,
            'usage': usage,
            'tool_calls': tool_calls,
            'finish_reason': 'tool_calls' if tool_calls else 'stop',
            'reasoning_content': msg.get('reasoning_content', ''),
        }
