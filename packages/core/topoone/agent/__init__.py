"""topoone.agent — Agent harness 服务（:3482）。

唯一 harness + 唯一 skill/tool 注册表；不含 provider 凭据，LLM 交互经 llm 服务通道。
入口: python -m topoone.agent。依赖内核 topoone.{db,rpc,messaging} + topoone.llm + topoone.engine（数据读取）。
"""
