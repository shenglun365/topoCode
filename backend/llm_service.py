"""LLM 后端服务 — 直接调用外部 LLM API

提供 summarize_code 等方法，供前端通过 ZeroMQ RPC 调用。
模型配置从 model_configs 表读取。
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

from zmq_server import ZMQServer
from sqlite_ctx import MultiDBManager

logger = logging.getLogger(__name__)


# ==================== 模型配置读取 ====================

def _get_default_model(multi_db: MultiDBManager) -> Optional[Dict[str, Any]]:
    """获取默认模型配置"""
    main_db = multi_db.main_db
    return main_db.fetchone("SELECT * FROM model_configs WHERE is_default = 1")


def _get_model_by_id(multi_db: MultiDBManager, model_id: str) -> Optional[Dict[str, Any]]:
    """按 ID 获取模型配置"""
    main_db = multi_db.main_db
    return main_db.fetchone("SELECT * FROM model_configs WHERE id = ?", (model_id,))


# ==================== LLM API 调用 ====================

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

    timeout = model_config.get('timeout', 120)
    resp = requests.post(f'{base_url}/api/chat', json=payload, timeout=timeout)
    if resp.status_code != 200:
        raise RuntimeError(f'Ollama API error {resp.status_code}: {resp.text}')
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

    timeout = model_config.get('timeout', 120)
    resp = requests.post(f'{base_url}/v1/chat/completions', json=payload, headers=headers, timeout=timeout)
    if resp.status_code != 200:
        raise RuntimeError(f'OpenAI API error {resp.status_code}: {resp.text}')
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
    elif provider in ('openai', 'custom', 'lmstudio'):
        return await asyncio.to_thread(_sync_call_openai_chat, model_config, messages)
    else:
        raise RuntimeError(f'Unsupported provider: {provider}')


# ==================== 业务方法 ====================

async def _summarize_code(
    multi_db: MultiDBManager,
    code: str,
    model_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    压缩长代码为伪码

    Args:
        code: 原始代码
        model_id: 指定模型 ID，None 则用默认模型

    Returns:
        { 'content': str, 'originalLength': int, 'summarizedLength': int }
    """
    if not code or len(code.strip()) == 0:
        raise ValueError('Code is empty')

    # 短代码不需要压缩
    if len(code) <= 500:
        return {
            'content': code,
            'originalLength': len(code),
            'summarizedLength': len(code),
            'compressed': False,
        }

    # 获取模型配置
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
    """
    解释代码符号

    Args:
        symbol_name: 符号名称
        symbol_type: 符号类型 (function/class/method/macro)
        code_snippet: 代码片段
        file_name: 文件路径
        model_id: 指定模型 ID
    """
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


async def _summarize_community_name(
    multi_db: MultiDBManager,
    node_count: int,
    edge_count: int,
    node_names: Optional[List[str]] = None,
    model_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    为社区生成简洁名称

    Args:
        node_count: 节点数
        edge_count: 边数
        node_names: 节点名称列表
        model_id: 指定模型 ID
    """
    if model_id:
        model = _get_model_by_id(multi_db, model_id)
    else:
        model = _get_default_model(multi_db)
    if not model:
        raise ValueError('No LLM model configured')

    system_prompt = (
        '你是一个代码架构命名助手。用户会提供一个代码社区的统计信息，'
        '请为其生成一个简洁的名称（不超过 10 个中文字）。只返回名称，不要其他内容。'
    )

    parts = [f'社区信息：{node_count} 个节点，{edge_count} 条边']
    if node_names and len(node_names) > 0:
        parts.append(f'节点列表：{", ".join(node_names[:20])}')
    parts.append('\n请为这个社区生成一个简洁的名称。')
    user_prompt = '\n'.join(parts)

    messages = [
        {'role': 'system', 'content': system_prompt},
        {'role': 'user', 'content': user_prompt},
    ]

    content = await _call_llm(model, messages)
    return {'content': content.strip()}


# ==================== 方法注册 ====================

def register_llm_methods(server: ZMQServer, multi_db: MultiDBManager):
    """注册 LLM 相关方法到 ZMQServer"""

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

    @server.register('llm.summarizeCommunityName')
    async def summarize_community_name(
        node_count: int,
        edge_count: int,
        node_names: Optional[List[str]] = None,
        model_id: Optional[str] = None,
    ):
        return await _summarize_community_name(multi_db, node_count, edge_count, node_names, model_id)

    # ==================== Chat 会话管理 ====================

    session_store: Dict[str, Dict[str, Any]] = {}  # 内存存储会话

    @server.register('chat.listSessions')
    def list_sessions():
        """列出所有会话"""
        sessions = []
        for sid, data in session_store.items():
            sessions.append({
                'id': sid,
                'title': data.get('title', '未命名'),
                'mode': data.get('mode', 'chat'),
                'status': 'idle',
                'messages': data.get('messages', []),
                'createdAt': data.get('createdAt', ''),
                'updatedAt': data.get('updatedAt', ''),
            })
        return {'sessions': sessions}

    @server.register('chat.createSession')
    def create_session(id: str, title: str, mode: str = 'chat'):
        """创建新会话"""
        now = datetime.now().isoformat()
        session_store[id] = {
            'title': title,
            'mode': mode,
            'messages': [],
            'createdAt': now,
            'updatedAt': now,
        }
        return {'id': id, 'title': title, 'mode': mode}

    @server.register('chat.deleteSession')
    def delete_session(id: str):
        """删除会话"""
        if id in session_store:
            del session_store[id]
        return {'success': True}

    @server.register('chat.saveMessage')
    def save_message(session_id: str, message: Dict[str, Any]):
        """保存消息到会话"""
        if session_id not in session_store:
            session_store[session_id] = {
                'title': '未命名',
                'mode': 'chat',
                'messages': [],
                'createdAt': datetime.now().isoformat(),
                'updatedAt': datetime.now().isoformat(),
            }
        session_store[session_id]['messages'].append(message)
        session_store[session_id]['updatedAt'] = datetime.now().isoformat()
        return {'success': True}

    return server
