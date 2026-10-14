"""turns — 回合引擎(L2, 整体设计 §4)。

M1 拆分(机械搬迁自 orchestrator, 行为等价):
- base.py     回合 IO/预算原语与常量
- context.py  阶段③ 消息装配(A 轴)
- chat.py     阶段④⑤⑥ 执行/落库(A 轴 chat 形态)
orchestrator 保留入口编排(gate/route/land 接线)并 re-export 阶段函数
(test_kb_chat_routing 五段结构守卫依赖该形状)。
"""
