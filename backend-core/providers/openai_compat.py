"""OpenAI-Compatible LLM Provider — BaseLLMProvider 实现

所有使用 OpenAI 格式 API 的提供商共用此基类:
- OpenAI (GPT-4, GPT-4o, GPT-3.5)
- DeepSeek (V2, V3, R1)
- Groq (LLaMA, Mixtral)
- LM Studio (本地模型, OpenAI-compatible 模式)
- Together AI, Fireworks AI, ...

API 格式: POST /v1/chat/completions
"""

import json as _json
import logging

import requests

from providers.base import BaseLLMProvider

logger = logging.getLogger(__name__)


class OpenAICompatProvider(BaseLLMProvider):
    """OpenAI 兼容 API 聊天补全 — 基类"""

    PROVIDER_NAME = 'openai-compat'
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
        }
        if model_config.get('temperature') is not None:
            payload['temperature'] = model_config['temperature']
        payload['max_tokens'] = model_config.get('max_tokens', 16384)

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

        _log_payload = {
            'provider': self.PROVIDER_NAME,
            'url': base_url + '/v1/chat/completions',
            'model': payload['model'],
            'mode': mode,
            'temperature': payload.get('temperature'),
            'max_tokens': payload.get('max_tokens'),
            'tools': list(payload.get('tools', [])) if payload.get('tools') else None,
            'messages': [
                {'role': m.get('role', ''), 'content_len': len(m.get('content') or ''), 'content_preview': (m.get('content') or '')[:3000]}
                for m in payload.get('messages', [])
            ],
        }
        logger.info(f"[LLM_REQ] {self.PROVIDER_NAME} 请求: {_json.dumps(_log_payload, ensure_ascii=False)}")

        full_content = ""
        tool_calls_parts = []
        usage_data = {}

        try:
            resp = requests.post(
                f'{base_url}/v1/chat/completions',
                json=payload, headers=headers, stream=True, timeout=timeout
            )
            if resp.status_code != 200:
                chunk_queue.put({'type': 'error', 'message': f'{self.PROVIDER_NAME} API error {resp.status_code}: {resp.text[:200]}'})
                chunk_queue.put({'type': 'done', 'content': ''})
                return token_info

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
                    break
                try:
                    data = _json.loads(data_str)
                    delta = data.get('choices', [{}])[0].get('delta', {})

                    if data.get('usage'):
                        usage_data = data['usage']

                    reasoning = delta.get('reasoning_content', '')
                    if reasoning:
                        chunk_queue.put({"type": "reasoning", "text": reasoning})
                    chunk = delta.get('content', '')
                    if chunk:
                        full_content += chunk
                        chunk_queue.put(chunk)

                    tc = delta.get('tool_calls')
                    if tc:
                        tool_calls_parts.append(_json.dumps(tc))
                except _json.JSONDecodeError:
                    continue

            if usage_data:
                token_info = {
                    'prompt_tokens': usage_data.get('prompt_tokens'),
                    'completion_tokens': usage_data.get('completion_tokens'),
                    'total_tokens': usage_data.get('total_tokens'),
                }
        except Exception as e:
            chunk_queue.put({'type': 'error', 'message': str(e)})
            chunk_queue.put({'type': 'done', 'content': ''})
            return token_info

        chunk_queue.put({'type': 'done', 'content': full_content})
        return token_info

    def chat_sync(
        self,
        model_config,
        messages,
        mode,
        tools=None,
        output_schema=None,
    ):
        base_url = model_config['url'].rstrip('/')
        if base_url.endswith('/v1'):
            base_url = base_url[:-3]
        payload = {
            'model': model_config['model'],
            'messages': messages,
            'stream': False,
        }
        if model_config.get('temperature') is not None:
            payload['temperature'] = model_config['temperature']
        payload['max_tokens'] = model_config.get('max_tokens', 16384)
        headers = {'Content-Type': 'application/json'}
        if model_config.get('api_key'):
            headers['Authorization'] = f"Bearer {model_config['api_key']}"

        if mode == 'tools' and tools:
            payload['tools'] = tools
            payload['tool_choice'] = 'auto'

        resp = requests.post(
            f"{base_url}/v1/chat/completions",
            json=payload, headers=headers,
            timeout=model_config.get('timeout', 300),
        )
        data = resp.json()
        choice = data.get('choices', [{}])[0]
        msg = choice.get('message', {})

        content = msg.get('content', '')
        usage = data.get('usage', {})

        # 解析原生 tool_calls
        raw_calls = msg.get('tool_calls', [])
        tool_calls = []
        if raw_calls:
            tool_calls = [
                {
                    "id": tc.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": tc.get("function", {}).get("name", ""),
                        "arguments": tc.get("function", {}).get("arguments", "{}"),
                    },
                }
                for tc in raw_calls
            ]

        return {
            'content': content,
            'usage': usage,
            'tool_calls': tool_calls,
            'finish_reason': choice.get('finish_reason', ''),
            'reasoning_content': msg.get('reasoning_content', ''),
        }


class OllamaProvider(OpenAICompatProvider):
    """Ollama 也支持 OpenAI 兼容 API (/v1/chat/completions)"""

    PROVIDER_NAME = 'Ollama'


class LmStudioProvider(OpenAICompatProvider):
    PROVIDER_NAME = 'LM Studio'


class DeepSeekProvider(OpenAICompatProvider):
    PROVIDER_NAME = 'DeepSeek'


class MiniMaxCNProvider(OpenAICompatProvider):
    PROVIDER_NAME = 'MiniMax-CN'


class MiniMaxGlobalProvider(OpenAICompatProvider):
    PROVIDER_NAME = 'MiniMax-Global'


class OpenRouterProvider(OpenAICompatProvider):
    PROVIDER_NAME = 'OpenRouter'


class CustomLocalProvider(OpenAICompatProvider):
    PROVIDER_NAME = 'Custom-Local'


class CustomCloudProvider(OpenAICompatProvider):
    PROVIDER_NAME = 'Custom-Cloud'
