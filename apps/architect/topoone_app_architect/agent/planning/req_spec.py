"""需求规约确定性链(规划层) — P4 机械迁入(逐字节保真, 仅导入升级)。

载荷签名识别/字段归一 → 确定性落库(apply_spec_payload) → L2 格式修复
→ 边界解析(parse_scope_files) → 提案围栏提取。契约由
test_fabrication_guard/test_probe_dossier/test_sessions_center 锁定。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger("arch.planning.req_spec")


# 惰性访问(P4): import 期零触发 arch_routes 初始化
def _store():
    from ... import store
    return store


def _ra():
    from ...agent.tools import req_agent
    return req_agent





# ── 规约载荷确定性提取(消息流「写入需求」按钮 / 守卫前置提取共用) ──

# 规约签名字段(识别+归一): 命中 ≥3 视为需求规约载荷
_SPEC_FIELD_ALIASES: Dict[str, tuple] = {
    "title": ("title", "name"),
    "requirementMd": ("requirementMd", "requirement", "requirement_md", "description"),
    "designMd": ("designMd", "design", "design_md"),
    "allowedScope": ("allowedScope", "allowedScopeMd", "allowed_scope", "allow", "scope"),
    "forbiddenScope": ("forbiddenScope", "forbiddenScopeMd", "forbidden_scope", "forbid", "antiGoals", "anti_goals"),
    "acceptance": ("acceptance", "acceptanceMd", "acceptance_md", "acceptanceCriteria"),
    "assessmentSummary": ("assessmentMd", "assessment", "assessment_md", "assessmentSummary"),
    "estMin": ("estMin", "est_min", "estimateMinutes"),
    "priority": ("priority",),
}


def is_spec_payload(obj: Any) -> bool:
    """字段签名识别: dict 且规约字段(别名归一后)命中 ≥3。"""
    if not isinstance(obj, dict):
        return False
    hit = 0
    for aliases in _SPEC_FIELD_ALIASES.values():
        if any(a in obj for a in aliases):
            hit += 1
    return hit >= 3


def _repair_json_like(raw: str) -> str:
    """LLM 伪 JSON 确定性自愈(零 LLM, 零误伤原则):

    - `\"\"\"...\"\"\"`(含 `\"\"\"\"` 多引号闭合)字符串(JSON 不支持, LLM 高频习惯)
      → 合法转义字符串;
    - 尾逗号 ` ,} ` / ` ,] ` → 删除。
    其余语法错误交给 L2(repair_spec_payload_format; 经 _ra() 解析保留 monkeypatch 接缝)。
    """
    def _tq(m: "re.Match") -> str:
        return json.dumps(m.group(1))
    raw = re.sub(r'"{3,}\s*(.*?)\s*"{3,}', _tq, raw, flags=re.DOTALL)
    raw = re.sub(r",(\s*[}\]])", r"\1", raw)
    return raw


def extract_spec_payload(text: str) -> Optional[Dict[str, Any]]:
    """从消息文本提取规约载荷(```json 围栏优先)。非规约形状 → None。

    - 嵌套围栏免疫: 值内可含 ```diagram 等子围栏(其 ``` 会截断非贪婪
      匹配)——对每个 ```json 起点逐个闭合候选(从近到远)尝试, 第一个
      loads 成功且规约形状胜出;
    - loads 失败先过 L0 伪 JSON 自愈(三引号/尾逗号)再判;
      is_spec_payload 字段签名校验兜底防误吸。
    """
    text = text or ""
    for jm in re.finditer(r"```json\s*", text):
        rest = text[jm.end():]
        for cm in re.finditer(r"```", rest):
            cand = rest[:cm.start()].strip()
            if not cand.startswith("{"):
                continue
            for raw in (cand, cand.rstrip().rstrip("`").rstrip()):
                try:
                    obj = json.loads(raw)
                except Exception:  # noqa: BLE001
                    try:
                        obj = json.loads(_repair_json_like(raw))
                    except Exception:  # noqa: BLE001
                        continue
                if is_spec_payload(obj):
                    return obj
    return None


def _norm_scope_list(v: Any) -> List[str]:
    """边界/验收字段: 数组或 markdown 字符串 → 行数组(级别 0 归一)。"""
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x or "").strip()]
    if isinstance(v, str):
        return [ln.strip().lstrip("-•* ").strip() for ln in v.splitlines() if ln.strip()]
    return []


def _plan_delivered(rid: str) -> bool:
    """绑定需求任务计划是否已交付完结(非空且全部 done; cv-248 归属三分判据)。

    taskPlan 从需求行直读(与 task_plan.get_plan 同源列, 避免内核反向依赖)。
    含非 done 步骤(进行中/失败待处理)=未交付完结 → 活跃需求走修订。"""
    if not rid:
        return False
    plan = (_store().RequirementsStore.get(rid) or {}).get("taskPlan") or []
    if isinstance(plan, str):
        try:
            plan = json.loads(plan)
        except (TypeError, ValueError):
            return False
    if not isinstance(plan, list) or not plan:
        return False
    return all(str((s or {}).get("status") or "") == "done"
               for s in plan if isinstance(s, dict))


def _fallback_title() -> str:
    """新建命名兜底链(cv-248): 会话标题·需求 → 需求——人不必想标题, 语义不丢。

    载荷 title 仍优先; 仅当载荷未给标题时兜底(需求是项目资产, RQ 编号唯一
    可辨识, 会话标题提供扫读语义)。"""
    try:
        from ... import ctx as _ctx
        conv = (_store().ConversationsStore.get(str(_ctx.get_conv() or "")) or {})
        t = str(conv.get("title") or "").strip()
        if t:
            return f"{t[:40]}·需求"
    except Exception:  # noqa: BLE001 — ctx 未设置/库不可达, 兜底到纯语义名
        pass
    return "需求"


def apply_spec_payload(payload: Dict[str, Any], req_id: str = "",
                       project: str = "", root: str = "") -> Dict[str, Any]:
    """规约载荷 → 确定性落库(零 LLM)。三级降级:

    L0 归一化自愈(别名/类型/围栏/兜底合并) → L1 字段降级(可选缺失忽略,
    ignored 报告) → L2 LLM 格式修复(repair_spec_payload_format, 产物再过本
    函数 L0/L1 + reqId 校验) → L3 如实失败。落库目标归属三分(cv-248 裁决):
    绑定需求**交付完结**(计划非空且全部 done / doneMark) → req.propose 新建
    (新编号/新 v1/载荷标题生效——内容互斥, 已完结旧内容不污染新需求; 会话
    绑定由 propose 内部翻页回写); 活跃需求(计划进行中/打磨期) → req.amend
    修订。载荷内 reqId 字段一律丢弃(防编造编号混入)。
    """
    ignored: List[str] = []
    errors: List[str] = []
    repaired = False
    aliased: List[str] = []
    known = {a for aliases in _SPEC_FIELD_ALIASES.values() for a in aliases}
    obj = {k: v for k, v in (payload or {}).items() if isinstance(k, str)}
    for k in list(obj.keys()):
        if k not in known:
            ignored.append(k)
            obj.pop(k)
    # L0: 别名归一
    norm: Dict[str, Any] = {}
    for canonical, aliases in _SPEC_FIELD_ALIASES.items():
        for a in aliases:
            if a in obj and obj[a] not in (None, ""):
                norm[canonical] = obj[a]
                if a != canonical:
                    aliased.append(f"{a}→{canonical}")
                break
    title = str(norm.get("title") or "").strip()
    design = str(norm.get("designMd") or "").strip()
    reqmd = str(norm.get("requirementMd") or "").strip()
    if not title and reqmd:
        title = reqmd.splitlines()[0][:60]
        aliased.append("requirementMd[0]→title")
    # L1: 字段降级(缺/空可选字段直接不传)
    assessment = norm.get("assessmentSummary")
    summary_txt = ""
    est_min = 0
    if isinstance(assessment, dict):
        parts = [f"{k}:{v}" for k, v in assessment.items() if k != "estMin" and v]
        summary_txt = "; ".join(str(x) for x in parts)
        try:
            est_min = int(assessment.get("estMin") or 0)
        except (TypeError, ValueError):
            pass
    elif assessment:
        summary_txt = str(assessment)
    if norm.get("estMin") and not est_min:
        try:
            est_min = int(norm.get("estMin"))
        except (TypeError, ValueError):
            errors.append("estMin 非整数, 已忽略")
    priority = str(norm.get("priority") or "").strip()
    allowed = _norm_scope_list(norm.get("allowedScope"))
    forbidden = _norm_scope_list(norm.get("forbiddenScope"))
    acceptance = _norm_scope_list(norm.get("acceptance"))
    # 落库目标判定(cv-248 归属三分): 交付完结的需求是已交付历史——新载荷
    # 立新需求(新编号/v1/标题生效); 活跃需求(计划进行中/打磨期)→ 修订演进。
    rid = (req_id or "").strip()
    row = _store().RequirementsStore.get(rid) if rid else None
    delivered = _plan_delivered(rid)
    can_amend = bool(row and (row.get("doneMark") or 0) != 1 and not delivered)
    if not title and not (reqmd or design or allowed or acceptance):
        # L2: 载荷实质缺失(标题+内容全空)才触发 LLM 修复; title 缺失但内容
        # 完整不再烧修复通道(修订不更名/新建走命名兜底链)
        fixed = _ra().repair_spec_payload_format(
            json.dumps(payload, ensure_ascii=False)[:6000], req_id=rid)
        if isinstance(fixed, dict):
            r = apply_spec_payload(fixed, req_id=rid, project=project, root=root)
            r["repaired"] = True
            if r.get("ok"):
                r["summary"] += "；格式已由修复通道修正"
            return r
        return {"ok": False, "action": "failed",
                "summary": "载荷缺少需求标题(title)，且格式修复通道未能产出有效规约",
                "errors": errors + ["signature-miss"], "ignored": ignored}
    args: Dict[str, Any] = {"title": title}
    if reqmd:
        args["requirementMd"] = reqmd
    if design:
        extra = ""
        impl_path = payload.get("implementationPath") if isinstance(payload, dict) else None
        if isinstance(impl_path, list) and impl_path:
            extra = ("\n\n## 实施路径\n"
                     + "\n".join(f"{i + 1}. {x}" for i, x in enumerate(impl_path)))
        asset_scope = payload.get("assetScope") if isinstance(payload, dict) else None
        if isinstance(asset_scope, list) and asset_scope:
            rows = [f"- {a.get('assetId')}({a.get('assetType')}/{a.get('role', '')})"
                    for a in asset_scope if isinstance(a, dict) and a.get("assetId")]
            extra += "\n\n## 资产范围\n" + "\n".join(rows)
        args["designMd"] = design + extra
    if allowed:
        args["allowedScopeMd"] = "\n".join(f"- {x}" for x in allowed)
    if forbidden:
        args["forbiddenScopeMd"] = "\n".join(f"- {x}" for x in forbidden)
    if acceptance:
        args["acceptanceMd"] = "\n".join(f"- {x}" for x in acceptance)
    if summary_txt:
        args["assessmentMd"] = summary_txt
    if est_min:
        args["estMin"] = est_min
    if priority in ("P0", "P1", "P2"):
        args["priority"] = priority
    if can_amend:
        args["reqId"] = rid
        # req.amend 签名是数组形态且不支持更名/评估分值——按目标分叉参数形状
        args.pop("title", None)
        args.pop("priority", None)
        args.pop("estMin", None)
        if title != rid and title:
            ignored.append("title(amend 不更名)")
        if "priority" in obj:
            ignored.append("priority(amend 不支持)")
        if est_min:
            ignored.append("estMin(amend 不支持)")
        if allowed:
            args["allowedScope"] = allowed
            args.pop("allowedScopeMd", None)
        if forbidden:
            args["forbiddenScope"] = forbidden
            args.pop("forbiddenScopeMd", None)
        if acceptance:
            args["acceptance"] = acceptance
            args.pop("acceptanceMd", None)
        if summary_txt:
            args["assessmentSummary"] = summary_txt
            args.pop("assessmentMd", None)
        args.setdefault("reasoning", "消息流「写入需求」确定性落库")
    else:
        args["newRequirement"] = True
        if not title:
            title = _fallback_title()
            aliased.append(f"兜底标题({title})")
            args["title"] = title
    # v2: 系统确定性落库路径(写入需求按钮/守卫代落)——internal 放行退役拦截。
    result = _ra().run_arch_tool("req.amend" if can_amend else "req.propose",
                           args, root=root, project=project, internal=True)
    if isinstance(result, dict) and result.get("error"):
        return {"ok": False, "action": "failed",
                "summary": f"落库执行失败: {str(result.get('error'))[:200]}",
                "errors": errors, "ignored": ignored, "repaired": repaired}
    out_rid = (result or {}).get("requirementId") or (result or {}).get("reqId") or rid
    out_ver = (result or {}).get("ver") or ""
    action = "amended" if can_amend else "proposed"
    notes = []
    if repaired:
        notes.append("格式已由修复通道修正")
    if delivered:
        notes.append("前需求计划已交付完结, 新目标立新需求")
    if aliased:
        notes.append("字段归一: " + ", ".join(aliased[:6]))
    if ignored:
        notes.append(f"忽略未知字段: {', '.join(ignored[:8])}")
    summary = (f"✅ 已按原文落库：`{out_rid}`"
               + (f" v{out_ver}" if out_ver else "")
               + f"（{'更新' if can_amend else '新建'}，经确定性映射，零模型转写）"
               + ("；" + "；".join(notes) if notes else ""))
    return {"ok": True, "action": action, "reqId": out_rid, "ver": out_ver,
            "summary": summary, "ignored": ignored, "repaired": repaired,
            "toolResult": result}


def repair_spec_payload_format(text: str, req_id: str = "") -> Optional[Dict[str, Any]]:
    """级别 2: 破损规约载荷的 LLM 格式修复(只修结构, 不发明内容)。

    产物需调用方再过 apply_spec_payload 的确定性校验; 一次尝试失败返回 None。
    """
    sys_prompt = (
        "你是需求规约载荷修复器。给定文本疑似一份需求规约的 JSON(可能语法破损/"
        "字段名不规范/被截断)。请只修复 JSON 结构与字段命名以匹配工具签名，"
        "不要新增不存在的信息，不要改动原本正确的字段值；无法恢复的字段留空或省略。\n"
        "目标字段: " + ", ".join(f"{c}({','.join(a[:3])})"
                                 for c, a in _SPEC_FIELD_ALIASES.items()) + "\n"
        + (f"会话绑定需求编号: {req_id}(载荷内其它 reqId 编号一律丢弃)\n" if req_id else "")
        + "只输出一个 ```json 围栏，内容为规约对象本身，不要任何其他文字。")
    from ..reflection.repair import RepairTask, run_repair_loop

    def _parse(raw: str):
        m = re.search(r"```json\s*(\{.*?})\s*```", raw, re.DOTALL)
        if not m:
            return None
        try:
            obj = json.loads(m.group(1))
            return obj if isinstance(obj, dict) else None
        except Exception:  # noqa: BLE001
            return None

    out = run_repair_loop(RepairTask(
        task_id="spec_format", system=sys_prompt, user=text[:6000],
        parse=_parse, dataset_kind="repair_spec_format"))
    return out.get("parsed") if isinstance(out.get("parsed"), dict) else None


# 需求规约 schema 特征字段(载荷归属判别的本域认领谓词——cv-246 架构裁决:
# 载荷归属由内容 schema 单源判别, 不由围栏标记/正则竞争决定)
_SPEC_SCHEMA_KEYS = ("requirementMd", "allowedScopeMd", "forbiddenScopeMd")

_JSON_FENCE_RE = re.compile(r"```(?:proposal|json)\s*\n?(\{.*?\})\s*```",
                            re.DOTALL)


def _is_spec_payload(d: Any) -> bool:
    """载荷是否需求规约形态(规约 schema 字段命中 ≥1)。"""
    return isinstance(d, dict) and any(
        str(d.get(k) or "").strip() for k in _SPEC_SCHEMA_KEYS)


def _iter_spec_payloads(text: str):
    """候选 JSON 围栏 → 规约形态载荷(提取与剥离共用的同源扫描)。"""
    for m in _JSON_FENCE_RE.finditer(text or ""):
        try:
            d = json.loads(m.group(1))
        except Exception:  # noqa: BLE001
            continue
        if _is_spec_payload(d):
            yield d


def strip_proposal_fence(text: str) -> str:
    """移除规约载荷围栏整体——与认领同源判定, 只剥规约 schema 载荷的围栏
    (不误伤图 IR/任务载荷等其它 json; proposal 显式围栏保持旧语义全剥)。"""
    if not text or "```" not in text:
        return text or ""
    out, hit = text, False
    for m in reversed(list(_JSON_FENCE_RE.finditer(text))):
        try:
            d = json.loads(m.group(1))
        except Exception:  # noqa: BLE001
            continue
        if _is_spec_payload(d):
            out, hit = out[:m.start()] + out[m.end():], True
    if not hit and "```proposal" in text:
        return re.sub(r"```proposal\s*\n?\{.*?\}\s*```", "",
                      text, flags=re.DOTALL).strip()
    return out.strip()


def extract_proposal_fence(text: str) -> Optional[Dict[str, Any]]:
    """提取需求规约载荷(方案生成的确定性落库通道; cv-246 归属判别)。

    生成类动作(产出提案)对部分模型而言"不需要工具"——它们更愿意直接把提案写成
    JSON 输出而非发 [TOOL_CALL]。围栏协议把这一行为变成可靠路径：模型写围栏，
    服务端解析后代为执行 req.propose 落库(WS 层发 tool_result 事件 → 前端方案卡)。
    认领谓词=内容 schema(规约字段命中), 不限围栏标记形态——```proposal 显式
    围栏与 json 围栏中的规约载荷同权; 任务形态载荷不认领(归 task 域)。
    """
    if not text or "```" not in text:
        return None
    for d in _iter_spec_payloads(text):
        return d
    m = re.search(r"```proposal\s*\n?(\{.*?\})\s*```", text, re.DOTALL)
    if not m:
        try:
            from ..reflection import dataset as _lds
            _lds.record("fence_parse", reason="未闭合/无JSON体",
                        tail=text[text.index("```proposal"):][:600])
        except Exception:  # noqa: BLE001
            pass
        return None
    try:
        data = json.loads(m.group(1))
        return data if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001
        try:
            from ..reflection import dataset as _lds
            _lds.record("fence_parse", reason="JSON解析失败",
                        tail=m.group(1)[:600])
        except Exception:  # noqa: BLE001
            pass
        return None


def _spec_snapshot(title: str, desc_md: str, design_md: str, allowed: list,
                   forbidden: list, acceptance: list, functional: list,
                   assessment: str, est_min: int) -> Dict[str, Any]:
    """规约版本快照(真相源结构)。"""
    # desc 是纯文本字段——剥离模型输出里混入的分节标题(否则
    # _instruction_from_snapshot 再包一层 → "## 需求目标"×2, cv-181 实证)
    desc = re.sub(r"^#{1,6}\s*(?:需求目标|目标|需求描述|需求)\s*\n+", "",
                  (desc_md or "").strip())
    return {
        "title": (title or "").strip(),
        "desc": desc,
        "designMd": design_md or "",
        "allowedScope": [str(x) for x in (allowed or [])][:40],
        "forbiddenScope": [str(x) for x in (forbidden or [])][:40],
        "acceptance": [str(x) for x in (acceptance or [])][:40],
        "functionalScope": [str(x) for x in (functional or [])][:40],
        "assessmentSummary": str(assessment or "")[:500],
        "estMin": int(est_min or 0),
    }


def _sync_analysis_cache(req_id: str, snapshot: Dict[str, Any]) -> None:
    """active 版本快照 → analysis 派生缓存(design/tagent_se/engine/ws 消费面零改动)。"""
    _store().RequirementsStore.update(req_id, {
        "analysis": {
            "functionalScope": snapshot.get("functionalScope") or [],
            "entityBoundary": [],
            "assessmentSummary": snapshot.get("assessmentSummary") or "",
            "assetScope": [],
            "estMin": snapshot.get("estMin") or 0,
            "implementationPath": str(snapshot.get("designMd") or "")[:500],
            "changes": [], "steps": [],
            "designMd": snapshot.get("designMd") or "",
            "allowedScope": snapshot.get("allowedScope") or [],
            "forbiddenScope": snapshot.get("forbiddenScope") or [],
            "acceptance": snapshot.get("acceptance") or [],
        },
        "desc": snapshot.get("desc") or "",
    })


def parse_scope_files(lines: list) -> set:
    """边界声明行 → 文件/目录集合(互斥引擎的文件级口径)。

    识别: 目录(以 / 结尾) · 文件路径(含 / 且带扩展名) · 顶层路径段(如 src/)。
    剥除括号补充说明——`modules/xxx/(更新目录结构及逻辑)` → `modules/xxx/`
    (全角/半角括号, 说明文字混入会稀释互斥前缀匹配精度)。
    组件引用(comp:xxx)与自然语言不参与文件级互斥(组件级经 KB 口径单独解析)。
    """
    import re as _re
    out: set = set()
    for ln in lines or []:
        t = str(ln or "").strip()
        if not t or t.startswith("comp:"):
            continue
        # 剥括号补充说明(全角/半角, 非嵌套)与常见前缀修饰
        t = _re.sub(r"[（(][^（）()]*[)）]", "", t).strip()
        for prefix in ("./", "/"):
            if t.startswith(prefix):
                t = t[len(prefix):]
        if not t or "/" not in t:
            continue
        out.add(t.rstrip("/"))
    return out
