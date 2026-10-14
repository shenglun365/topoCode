"""topoone.llm — LLM 模型网关服务（:3484）。

唯一持 provider 凭据、唯一 LLM 客户端。入口: python -m topoone.llm。
依赖内核 topoone.{db,rpc,messaging}；被 agent/chat/architect 经 HTTP(/zmq/llm.*) + PUB 5682 依赖。
"""
