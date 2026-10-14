"""核心资产评估落地(2610 P2)——执行终态自动 post-flight → 会话评估卡 + units 沉淀。

三联动(评估性, 非阻断): 结构化文字(裁决/命中清单) + 组件影响半径(结构) +
触及文件/资产坐标(代码锚点)。双通道共用: proxy 泵 finally / 任务链 on_finished。

分层: 本模块(agent 层)落卡(cards.land)与沉淀(store); 评估计算在 sem/core_guard。
"""
from __future__ import annotations

import logging
from typing import List, Optional

logger = logging.getLogger("arch_routes.exec_bridge")


def land_core_assessment(conv_id: str, project_id: str,
                         changed_files: List[str],
                         source: str = "") -> Optional[dict]:
    """执行终态核心资产评估落地(无命中零动作; 配置门控与 pre-flight 同键)。

    - 会话卡: kind=asset_assess(items 统一投影 → FE AssetAssessCard)
    - units 沉淀: type=core_assess(命中即 importance=1; 2610 重构无分级)——
      供 architect/执行器 ctx.search 检索复用。
    """
    if not project_id or not changed_files:
        return None
    try:
        from ... import store
        from ..compensation.overrides import override_enabled, read_overrides
        from ...sem import core_guard as _cg
        if not override_enabled(read_overrides(store.CollabConfigStore.get),
                                _cg.CONFIG_KEY):
            return None
        report = _cg.postflight_report(project_id, changed_files)
        if not report:
            return None
        payload = {
            "verdict": report["extent"]["verdict"],
            "hitRatio": report["extent"]["hitRatio"],
            "totalChanged": report["totalChanged"],
            "hitChanged": report["hitChanged"],
            "marks": report["marks"][:10],
            "hitFiles": report.get("hitFiles") or [],
            "assetImpact": report.get("assetImpact") or [],
            "componentRadius": report.get("componentRadius") or [],
            "source": source[:60],
        }
        from . import exec_bridge as eb
        # 会话评估卡(结构化 payload 经 item 投影渲染; 正文兜底可读 md)
        verdict_cn = {"light": "轻", "medium": "中", "heavy": "重"}[payload["verdict"]]
        body = (f"🛡 核心资产评估（{verdict_cn}）——改动 {payload['totalChanged']} 文件, "
                f"触及核心标记 {payload['hitChanged']} 个"
                + "。评估性结论, 不阻断。")
        eb._append(conv_id, "assistant", body,
                   msg_meta={"kind": "asset_assess", **payload})
        # units 沉淀(检索复用: 标题+命中清单+规约)
        try:
            unit_md = _cg.postflight_md(project_id, changed_files)
            store.ContextUnitsStore.create({
                "conversationId": conv_id, "projectId": project_id,
                "type": "core_assess",
                "title": f"核心资产评估·{verdict_cn}"
                         f"({'/'.join(m['title'] for m in payload['marks'][:3])})",
                "content": (unit_md or body)[:4000],
                "refs": {"files": payload["hitFiles"][:20],
                         "marks": [m.get("title") for m in payload["marks"]]},
                "importance": 1,
            })
        except Exception as e:  # noqa: BLE001 — 沉淀失败不阻断卡
            logger.debug("[core-assess] units 沉淀失败 conv=%s: %s", conv_id, e)
        logger.info("[core-assess] conv=%s 命中 %s 标记(%s) source=%s",
                    conv_id, payload["hitChanged"], verdict_cn, source)
        return payload
    except Exception as e:  # noqa: BLE001 — 评估落地失败不影响主链
        logger.warning("[core-assess] conv=%s 评估落地失败: %s", conv_id, e)
        return None


def files_of_job_diff(job_id: str) -> List[str]:
    """runner 就地只读 diff → 变更文件清单(轻量, 失败空)。"""
    try:
        from . import exec_bridge as eb
        d = eb._runner(f"/api/implement/{job_id}/diff", None, 12.0) or {}
        if d.get("ok") is False:
            return []
        return [str(f) for f in (d.get("changedFiles") or []) if f][:400]
    except Exception:  # noqa: BLE001
        return []
