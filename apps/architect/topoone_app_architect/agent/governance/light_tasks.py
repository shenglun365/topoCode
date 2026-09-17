"""轻任务模型(编码编排侧) — 纯函数层(零 IO, R1 棘轮合规)。

与「资产助理」(cognition/roles.py, 数据资产·语义提取管线工种)是**两个领域**:
本模块服务编码编排侧的轻任务(会话标题/摘要、范围探针), 它们默认跟随主对话
模型(可能为强档)——单独绑小档可节省强档算力(M3 mixed-fleet 裁决: 按领域
分列命名, 不复用「角色」词)。

配置单源: CollabConfigStore 键 `llm.lightTaskModels` = JSON
  {"summary": "<modelId>", "probe": "<modelId>"}   # 空串 = 跟随现行为
键仅两个: 标题与摘要由同一次 summarize_task 生成(单一绑定, 不设 title 死键)。

分层(依赖注入): 本模块只做纯校验/纯读取——存储读写与模型目录校验留在
arch_routes.agent_roles 适配层; 消费方(memory.units / planning.scope_probe,
均在 R1 冻结清单)自行加载 cfg dict 传入 resolve。消费方式为 **per-call
model_id 参数**(护栏 R3)。
"""
from __future__ import annotations

from typing import Any, Dict, Iterable

# 轻任务词汇表: 任务名 → 用途说明(写路径只接受这些键; 消费点一一对应)
LIGHT_TASKS: Dict[str, str] = {
    "summary": "会话标题/摘要生成(memory.units summarize_conversation)",
    "probe": "范围探针 grounding 补全(planning.scope_probe)",
}

LIGHT_TASKS_KEY = "llm.lightTaskModels"


def light_tasks_vocab() -> Dict[str, str]:
    return dict(LIGHT_TASKS)


def normalize_light_tasks(data: Any, known_ids: Iterable[str] = ()) -> Dict[str, str]:
    """写入前校验(纯): 仅接受词表键; modelId 越界剥离(防网关静默回退 KB 默认)。

    known_ids 为空(目录未同步/新装)时跳过越界校验, 不误伤。
    """
    known = set(known_ids or ())
    out: Dict[str, str] = {}
    src = data if isinstance(data, dict) else {}
    for k in LIGHT_TASKS:
        mid = str(src.get(k) or "").strip()
        if mid and known and mid not in known:
            out[k] = ""
            continue
        out[k] = mid
    return out


def resolve_light_task_model(task: str, cfg: Any) -> str:
    """轻任务 → 配置的 modelId(空串 = 调用方回退现行为/全局偏好)。

    纯函数: cfg 为原始 dict(可残缺/含未知键); 坏输入一律空串, 绝不抛出
    (轻任务路由失败不得影响主链)。
    """
    if not task or not isinstance(cfg, dict):
        return ""
    mid = cfg.get(task)
    return str(mid).strip() if isinstance(mid, str) else ""
