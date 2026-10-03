"""语义资产解析能力探测(批4) — 独立套件, 与 architect 综合档分离。

裁决(2026-10-03): 资产解析能力单独测试单独定档(需求与 architect 能力
有差异), 结果与综合档共用 modelProfiles 表、独立 `asset` 字段保存;
档位体系纯参数化(mode/listCap/chainLen/retries, 无硬性档位边界)。

批0 实测结论(324 调用/18 模型)内化为探测设计:
- 10 次调用(用户裁决 5-10 次测稳定性): name@100×3 + num@100×3 +
  num@200×2 + len@15×2;
- 判定用各档最小采样(0/1 摆动模型均值会虚高);
- 通过档 = min(采样) ≥ 0.9; numMax ≥ nameMax → numbered(编号引用,
  数字抄录远稳于长中文名); name 稳 → free; 都不稳 → structural
  (图算法构链, LLM 仅命名——len@15 几乎全稳)。
"""
from __future__ import annotations

import logging
import random
import re
import time
from typing import Dict, List, Optional

logger = logging.getLogger("arch.asset_probe")

PASS = 0.9          # 档位通过线(最小采样)
ROW_CHARS = 160     # 资产数 → 清单 chars 的粗略换算(_assets_brief 行均长)

_VERBS_CN = ["解析", "构建", "计算", "渲染", "校验", "压缩", "合并", "分发", "缓存",
             "序列化", "归一化", "聚合", "过滤", "转换", "提取", "注册", "调度", "捕获"]
_NOUNS_CN = ["位移", "拓扑", "快照", "节点", "边集", "图层", "帧序列", "场景", "脚本",
             "属性", "样式", "事件", "状态", "路由", "契约", "布局", "锚点", "文档", "补间"]
_VERBS_EN = ["parse", "build", "calc", "render", "validate", "compact", "merge", "dispatch",
             "cache", "serialize", "normalize", "aggregate", "filter", "convert", "extract",
             "register", "schedule", "capture"]
_NOUNS_EN = ["Displacement", "Topology", "Snapshot", "Node", "Edges", "Layer", "Frames",
             "Scene", "Script", "Attrs", "Style", "Events", "State", "Route", "Contract",
             "Layout", "Anchors", "Doc", "Tween"]


def _norm(s: str) -> str:
    t = re.sub(r"[（(【\[].*?[)）\]】]", "", s or "")
    return re.sub(r"\s+", "", t).lower()


def synth_assets(n: int) -> List[dict]:
    """合成资产清单(固定 seed 可复现; 形态对齐真实库)。"""
    rng = random.Random(42)
    pairs = [(f"{v}{u}", f"{e}{w}") for v, e in zip(_VERBS_CN, _VERBS_EN)
             for u, w in zip(_NOUNS_CN, _NOUNS_EN)]
    rng.shuffle(pairs)
    return [{"name": nm, "symbol": sym, "desc": f"负责{nm}的处理逻辑",
             "file": f"src/core/m{i % 12}.ts"} for i, (nm, sym) in enumerate(pairs[:n])]


def _extract_json(raw: str):
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        return json_loads(raw)
    except Exception:
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            return None
        try:
            return json_loads(m.group(0))
        except Exception:
            return None


def json_loads(s: str):
    import json
    return json.loads(s)


_SYS_NAME = ("你是资深软件架构分析师。请从下列实现级资产清单中归纳数据加工链条："
             "每条链 4-8 个成员，members 必须逐字引用清单中的「资产名」。"
             '只输出 JSON：{"chains":[{"name":"链名","summary":"一句话",'
             '"members":["资产名", ...]}]}，共 5 条。')
_SYS_NUM = ("你是资深软件架构分析师。请从下列编号资产清单中归纳数据加工链条："
            "每条链 4-8 个成员，members 输出清单行首的编号数字数组。"
            '只输出 JSON：{"chains":[{"name":"链名","summary":"一句话",'
            '"members":[12, 30, ...]}]}，共 5 条。')
_SYS_LEN = ("你是资深软件架构分析师。给下列协作完成一个数据加工过程的成员序列起一个"
            "链名并概括一句话。只输出 JSON："
            '{"name":"链名(≤14字)","summary":"一句话概括(≤50字)"}。')


def _brief(assets: List[dict], numbered: bool) -> str:
    lines = []
    for i, a in enumerate(assets, 1):
        head = f"[{i}] " if numbered else "- "
        lines.append(f"{head}[asset] {a['name']} (sym:{a['symbol']}): {a['desc']}\n"
                     f"  文件:{a['file']} 符号:{a['symbol']}")
    return "\n".join(lines)


def score_name_recall(raw: str, assets: List[dict]) -> float:
    """名称回引得分: members 命中清单(norm 归一)比例。"""
    valid = {_norm(a["name"]) for a in assets}
    parsed = _extract_json(raw)
    tot = hit = 0
    if isinstance(parsed, dict):
        for ch in (parsed.get("chains") or [])[:8]:
            for m in (ch.get("members") or []):
                tot += 1
                if _norm(str(m)) in valid:
                    hit += 1
    return round(hit / tot, 3) if tot else 0.0


def score_numbered_recall(raw: str, assets: List[dict]) -> float:
    """编号回引得分: members 有效编号(1..N)比例。"""
    n = len(assets)
    parsed = _extract_json(raw)
    tot = hit = 0
    if isinstance(parsed, dict):
        for ch in (parsed.get("chains") or [])[:8]:
            for m in (ch.get("members") or []):
                tot += 1
                try:
                    hit += 1 if 1 <= int(m) <= n else 0
                except (TypeError, ValueError):
                    pass
    return round(hit / tot, 3) if tot else 0.0


def score_chain_naming(raw: str) -> int:
    """链长容忍(命名概括)得分: JSON 合规 + name 非空 → 1/0。"""
    parsed = _extract_json(raw)
    return 1 if isinstance(parsed, dict) and str(parsed.get("name") or "").strip() else 0


def _cases() -> List[dict]:
    """10 次调用编排(用户裁决 5-10 次稳定性采样)。"""
    return ([{"kind": "name@100", "sys": _SYS_NAME, "n": 100, "numbered": False} for _ in range(3)]
            + [{"kind": "num@100", "sys": _SYS_NUM, "n": 100, "numbered": True} for _ in range(3)]
            + [{"kind": "num@200", "sys": _SYS_NUM, "n": 200, "numbered": True} for _ in range(2)]
            + [{"kind": "len@15", "sys": _SYS_LEN, "n": 15, "numbered": False} for _ in range(2)])


def probe_asset_capability(model_id: str, *, force: bool = False) -> dict:
    """探测主入口: 10 次调用 → 参数推导 → 档案落库(独立 asset 字段)。

    并发治理: 复用 model_profile._ProbeGate(全局串行, 同模型滤重)。
    """
    from . import model_profile as MP
    if not force and (MP.get_profile(model_id).get("asset") or {}).get("source") == "probed":
        return {"skipped": True, "reason": "already_probed"}
    token = MP._probe_gate.enter(model_id)   # 复用全局串行闸(与综合档探测互斥)
    try:
        return _probe_locked(model_id)
    finally:
        MP._probe_gate.leave(model_id)


def _probe_locked(model_id: str) -> dict:
    from .llm import llm_sync   # 同包(agent.cognition)相对导入
    evidence: Dict[str, list] = {}
    for c in _cases():
        assets = synth_assets(c["n"])
        user = ("实现级资产：\n" if not c["numbered"] else "实现级资产(编号)：\n") \
            + _brief(assets, c["numbered"])
        if c["kind"] == "len@15":
            seq = " → ".join(f"{a['name']}({a['symbol']})" for a in assets)
            user = f"成员序列({c['n']} 个)：\n{seq}"
        user += "\n\n请输出 JSON。"
        try:
            res = llm_sync([{"role": "system", "content": c["sys"]},
                            {"role": "user", "content": user}],
                           mode="chat", model_id=model_id)
            raw = ((res or {}).get("content") or "") if res else ""
        except Exception as e:  # noqa: BLE001 — 单用例失败记 0 分继续
            logger.warning("[asset-probe] 用例异常 %s %s: %s", model_id, c["kind"], e)
            raw = ""
        if c["kind"] == "len@15":
            sc = score_chain_naming(raw)
        elif c["numbered"]:
            sc = score_numbered_recall(raw, assets)
        else:
            sc = score_name_recall(raw, assets)
        evidence.setdefault(c["kind"], []).append(sc)
    profile = derive_asset_profile(evidence)
    profile.update({"source": "probed", "updatedAt": int(time.time() * 1000)})
    _save_asset_profile(model_id, profile)
    logger.info("[asset-probe] %s → mode=%s listCap=%s evidence=%s",
                model_id, profile["mode"], profile.get("listCap"), evidence)
    return {"modelId": model_id, "profile": profile, "evidence": evidence}


def derive_asset_profile(evidence: Dict[str, list]) -> dict:
    """证据 → 参数推导(纯函数, 批0 结论内化)。

    通过档 = min(采样) ≥ PASS; numMax ≥ nameMax → numbered; name 稳 → free;
    都不稳 → structural(构链, LLM 仅命名)。retries: 全稳 1 次否则 2。
    """
    def passed(kind: str) -> bool:
        v = evidence.get(kind) or []
        return bool(v) and min(v) >= PASS

    name_max = 100 if passed("name@100") else 0
    num_max = 200 if passed("num@200") else (100 if passed("num@100") else 0)
    len_ok = passed("len@15")
    if num_max >= max(name_max, 100):
        mode, list_cap = "numbered", num_max
    elif name_max >= 100:
        mode, list_cap = "free", name_max
    else:
        mode, list_cap = "structural", None
    stable = all(min(v) >= 0.95 for v in evidence.values() if v)
    return {"mode": mode, "listCap": list_cap,
            "chainLen": [3, 15] if len_ok else [3, 10],
            "retries": 1 if stable else 2,
            "evidence": evidence}


def _save_asset_profile(model_id: str, asset: dict) -> None:
    """档案落库: modelProfiles 共表、独立 asset 字段(不动 tier/source)。"""
    from . import model_profile as MP
    import json
    data = json.loads(MP._store().CollabConfigStore.get(MP._PROFILES_KEY, "") or "{}")
    prof = data.get(model_id) or {}
    prof["asset"] = asset
    data[model_id] = prof
    MP._store().CollabConfigStore.set(MP._PROFILES_KEY, json.dumps(data, ensure_ascii=False))


def set_asset_profile_manual(model_id: str, asset: Optional[dict]) -> dict:
    """手动覆盖(参数级, source=manual 优先于 probed; None=清除回缺省)。"""
    if asset is None:
        from . import model_profile as MP
        import json
        data = json.loads(MP._store().CollabConfigStore.get(MP._PROFILES_KEY, "") or "{}")
        prof = data.get(model_id) or {}
        prof.pop("asset", None)
        if prof:
            data[model_id] = prof
        else:
            data.pop(model_id, None)
        MP._store().CollabConfigStore.set(MP._PROFILES_KEY, json.dumps(data, ensure_ascii=False))
        return {"modelId": model_id, "asset": None}
    asset = dict(asset)
    asset["source"] = "manual"
    asset["updatedAt"] = int(time.time() * 1000)
    _save_asset_profile(model_id, asset)
    return {"modelId": model_id, "asset": asset}


def asset_parse_policy(model_id: str) -> dict:
    """归纳消费口径: asset 档案 → induce 参数(mode/ref_form/brief_cap)。

    未探测/缺省 → 现行为(free+名称引用不分批); manual/probed 参数直用。
    """
    from . import model_profile as MP
    prof = (MP.get_profile(model_id).get("asset") or {}) if model_id else {}
    mode = prof.get("mode") or ""
    list_cap = prof.get("listCap") or 0
    brief_cap = int(list_cap * ROW_CHARS) if list_cap else None
    if mode == "numbered":
        return {"mode": "free", "ref_form": "num",
                "brief_cap": brief_cap, "retries": prof.get("retries") or 1}
    if mode == "structural":
        return {"mode": "structural", "ref_form": "name", "brief_cap": None,
                "chain_len": prof.get("chainLen") or [3, 15],
                "retries": prof.get("retries") or 1}
    if mode == "free":
        return {"mode": "free", "ref_form": "name",
                "brief_cap": brief_cap, "retries": prof.get("retries") or 1}
    return {"mode": "free", "ref_form": "name", "brief_cap": None, "retries": 1}
