"""补偿白名单开关(R1 白名单行为变更的回退通道, 整体设计 §6)。

全局 config 键 `agent.comp.overrides`(CollabConfigStore, JSON 对象):
    {"r2_1_axis_stack": true, "r2_3_probe_fallback": true,
     "p_axis_phase_overlay": true, "flow_guards_enabled": true, ...}
语义: 键缺省 = 新行为(白名单已评审); 显式 false = 回退旧行为(可逐项回退)。

流程相位机开关(R3 开关矩阵, governance/flow.py 裁决):
- p_axis_phase_overlay: P 轴策略叠加(resolve_gear 相位→对话面指引); false = 回退
  flow-blind(相位不进策略)。
- flow_guards_enabled: 相位硬闸(orchestrator 阶段①.5, 仅 interrupted 拦下发);
  false = 回退无守卫。derive(相位缓存本体)恒开无开关——纯缓存零行为。

反思闭环注入开关(采纳文档 2609 P0, 规则数值走 agent.flow.policy):
- repair_note_injection: 修复经验回填+装配注入(S1); false = 不落单元不注入。
- overflow_digest: 工作记忆溢出摘要注入(S3); false = 维持定长截断现状。
- swallow_counters: 装配路径吞错计数(S2); false = 计数器停走(零行为差异)。

受限 LLM 意图分类(GU-L2, 2026-09-22 归位):
- ~~intent_llm_fallback~~ **已取代**: 开关迁 `agent.flow.policy → goal.escalation.
  llmFallback`(缺省关, 与置信/长度门槛同处一键); 本键不再读取。
  LLM 意图只参与 GoalProfile 升格(回合指引仍走决策表), 永不入相位硬闸(防守线①)。
本模块零依赖(getter 注入), 供 turns/exec_bridge 等读取点传入 store 取数函数。
"""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, Optional

OVERRIDES_KEY = "agent.comp.overrides"


def read_overrides(getter: Optional[Callable[[str, Any], Any]]) -> Dict[str, Any]:
    """读取 overrides 配置(getter 注入, 读取失败 → 空表 = 全部默认新行为)。"""
    if getter is None:
        return {}
    try:
        raw = getter(OVERRIDES_KEY, "")
        data = json.loads(raw) if raw else {}
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 — 配置损坏不阻塞主链
        return {}


def override_enabled(overrides: Dict[str, Any], key: str) -> bool:
    """开关语义: 缺省开启(新行为); 显式 false 回退旧行为。"""
    return bool(overrides.get(key, True))
