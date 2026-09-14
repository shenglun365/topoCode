"""architect agent 九层内核(P0-P6 重构完成)。

分层与落位:
    orchestrator    回合编排: perceive → route → (cognition ↔ tools)* → fence → reflect → persist
    perception/     ① 交互感知/目的识别: gate(会话闸门) router(收件人路由) intent(意图正则)
    cognition/      ② 认知与控制(LLM): llm roles model_profile strategy prompt
    planning/       ③ 规划层: req_spec(需求规约确定性链) task_plan(任务卡/指令组装)
    memory/         ④ 记忆管理: units(上下文注册表) dossier(装配) working(历史窗口)
    tools/          ⑤ 工具与行动: registry(注册表) protocol(TOOL_CALL 协议)
    execution/      ⑥ 执行层: pumps(单泵) runner_client(类型化访问端)
    reflection/     ⑦ 反思学习: guards repair evaluator mining dataset
    collab/         ⑧ 协作通信: sse(进程内事件总线)
    governance/     ⑨ 安全与治理: boundary(边界/互斥/越界)

边界纪律:
  - 分层单向依赖; ⑦⑧⑨ 为横切面(经接口/回调注入 orchestrator)
  - arch_routes/*.py 保留为 REST/WS 适配层(契约冻结, CONV-04);
    兼容 shim(ws_events/llm_dataset/model_profile/prompt_registry/agent_roles/
    adaptation/context_registry/capability_mining/evaluator + req_agent 内
    re-export)保持存量 import 与测试 monkeypatch 接缝, 撤除待外圈调用方迁移
  - agent 包内模块禁止 import 期触发 arch_routes 初始化(store/ctx 等一律
    函数级惰性引用, 循环导入防线)

重构历程与契约: docs/architect-reconstruction/nine-layer-refactor.md
特征测试基线: apps/architect/tests/test_kb_chat_routing.py 等(P0 固化)
"""
