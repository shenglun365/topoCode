"""topoone.engine — 核心引擎（导入/解析/符号图/社区/任务/版本/导出校验）+ kb 进程入口。

依赖内核 topoone.{db,rpc,messaging}；禁止 import llm/agent（需 LLM 走 llm 服务 HTTP 通道）。
"""
