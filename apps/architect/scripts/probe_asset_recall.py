#!/usr/bin/env python3
"""语义资产解析能力批量探测(批0 前置评估) — dev 脚本, 不进产品链路。

对 architect llm.models 全部 LMS 模型实测(裁决 2026-10-03: 语义资产解析
能力单独测试单独定档, 与 architect 综合档分离; 本脚本先行评估档位阈值):

  A) 名称回引: 清单@50/100/200 ×2 采样 → 成员名命中率(free 策略遵循度)
  B) 编号回引: 清单@100/200 ×2 → 有效编号率(numbered 策略遵循度)
  C) 链长容忍: 链长 3/6/10/15 ×2 → JSON 合规 + 命名质量(结构化构链参数)

输出: /tmp/opencode/asset_probe_results.jsonl(逐条 append, 断点续跑——
已完成的 (model, case) 跳过) + 终端汇总表。合成清单固定 seed 可复现。
"""
from __future__ import annotations

import json
import random
import re
import time
import urllib.request

BASE = "http://10.0.0.75:1234/v1/chat/completions"
ARCH_API = "http://localhost:3470/api/architect/llm/models"
OUT = "/tmp/opencode/asset_probe_results.jsonl"
SEED = 42

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


def synth_assets(n: int) -> list[dict]:
    """合成资产清单(固定 seed): 中文名 + camelCase 符号 + 描述(形态对齐真实库)。"""
    rng = random.Random(SEED)
    pairs = [(f"{v}{u}", f"{e}{w}") for v, e in zip(_VERBS_CN, _VERBS_EN)
             for u, w in zip(_NOUNS_CN, _NOUNS_EN)]
    rng.shuffle(pairs)
    out = []
    for i, (nm, sym) in enumerate(pairs[:n]):
        out.append({"name": nm, "symbol": sym,
                    "desc": f"负责{nm}的处理逻辑，模块{i % 9 + 1}的核心步骤",
                    "file": f"src/core/m{i % 12}/mod{i % 12}.ts"})
    return out


def _norm(s: str) -> str:
    t = re.sub(r"[（(【\[].*?[)）\]】]", "", s or "")
    return re.sub(r"\s+", "", t).lower()


def chat(model: str, sys_p: str, user_p: str, timeout: int = 240) -> str:
    body = json.dumps({"model": model,
                       "messages": [{"role": "system", "content": sys_p},
                                    {"role": "user", "content": user_p}],
                       "max_tokens": 4096, "temperature": 0.7}).encode()
    req = urllib.request.Request(BASE, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read().decode())
    return ((d.get("choices") or [{}])[0].get("message") or {}).get("content") or ""


def _extract_json(raw: str):
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        return json.loads(raw)
    except Exception:
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except Exception:
            return None


SYS_CHAIN = ("你是资深软件架构分析师。请从下列实现级资产清单中归纳数据加工链条："
             "每条链 4-8 个成员，members 必须逐字引用清单中的「资产名」。"
             '只输出 JSON：{"chains":[{"name":"链名","summary":"一句话",'
             '"members":["资产名", ...]}]}，共 5 条。')

SYS_NUM = ("你是资深软件架构分析师。请从下列编号资产清单中归纳数据加工链条："
           "每条链 4-8 个成员，members 输出清单行首的编号数字数组。"
           '只输出 JSON：{"chains":[{"name":"链名","summary":"一句话",'
           '"members":[12, 30, ...]}]}，共 5 条。')

SYS_NAME = ("你是资深软件架构分析师。给下列协作完成一个数据加工过程的成员序列起一个"
            "链名并概括一句话。只输出 JSON："
            '{"name":"链名(≤14字)","summary":"一句话概括(≤50字)"}。')


def brief_lines(assets: list[dict], numbered: bool) -> str:
    lines = []
    for i, a in enumerate(assets, 1):
        head = f"[{i}] " if numbered else "- "
        lines.append(f"{head}[asset] {a['name']} (sym:{a['symbol']}): {a['desc']}\n"
                     f"  文件:{a['file']} 符号:{a['symbol']}")
    return "\n".join(lines)


def case_name_recall(model: str, n: int) -> dict:
    assets = synth_assets(n)
    valid = {_norm(a["name"]) for a in assets}
    raw = chat(model, SYS_CHAIN, "实现级资产：\n" + brief_lines(assets, False) + "\n\n请输出 JSON。")
    parsed = _extract_json(raw)
    tot = hit = 0
    if isinstance(parsed, dict):
        for ch in (parsed.get("chains") or [])[:8]:
            for m in (ch.get("members") or []):
                tot += 1
                if _norm(str(m)) in valid:
                    hit += 1
    return {"case": f"name@{n}", "ok": tot > 0, "total": tot, "hit": hit,
            "rate": round(hit / tot, 3) if tot else 0.0,
            "json_ok": parsed is not None, "chars": len(raw)}


def case_numbered_recall(model: str, n: int) -> dict:
    assets = synth_assets(n)
    raw = chat(model, SYS_NUM, "实现级资产(编号)：\n" + brief_lines(assets, True) + "\n\n请输出 JSON。")
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
    return {"case": f"num@{n}", "ok": tot > 0, "total": tot, "hit": hit,
            "rate": round(hit / tot, 3) if tot else 0.0,
            "json_ok": parsed is not None, "chars": len(raw)}


def case_chain_len(model: str, k: int) -> dict:
    assets = synth_assets(k)
    seq = " → ".join(f"{a['name']}({a['symbol']})" for a in assets)
    raw = chat(model, SYS_NAME, f"成员序列({k} 个)：\n{seq}\n\n请输出 JSON。")
    parsed = _extract_json(raw)
    name_ok = bool(isinstance(parsed, dict) and str(parsed.get("name") or "").strip())
    return {"case": f"len@{k}", "ok": name_ok, "name_ok": name_ok,
            "json_ok": parsed is not None, "chars": len(raw)}


# 注意: lambda 默认参数固化档位值(闭包晚绑定会让全部用例跑最后一档)
CASES = ([("A", lambda m, n=n: case_name_recall(m, n)) for n in (50, 100, 200) for _ in range(2)]
         + [("B", lambda m, n=n: case_numbered_recall(m, n)) for n in (100, 200) for _ in range(2)]
         + [("C", lambda m, k=k: case_chain_len(m, k)) for k in (3, 6, 10, 15) for _ in range(2)])


def architect_lms_models() -> list[str]:
    with urllib.request.urlopen(ARCH_API, timeout=10) as r:
        d = json.loads(r.read().decode())
    models = ((d.get("data") or {}).get("models")) or []
    return [m["model"] for m in models
            if "10.0.0.75:1234" in (m.get("url") or "") and m.get("model")]


def main() -> None:
    done = set()
    try:
        with open(OUT, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                    done.add((r.get("model"), r.get("case")))
                except Exception:
                    pass
    except FileNotFoundError:
        pass
    models = architect_lms_models()
    print(f"模型 {len(models)} 个 × 用例 {len(CASES)} 项(已完成 {len(done)} 跳过)", flush=True)
    for mid in models:
        for i, (_, fn) in enumerate(CASES):
            if (mid, fn.__name__ + str(i)) in done or any(
                    k[0] == mid and k[1] == f"case{i}" for k in done):
                pass
            t0 = time.time()
            try:
                r = fn(mid)
                r.update({"model": mid, "ts": int(time.time() * 1000),
                          "latency": int(time.time() - t0)})
                with open(OUT, "a", encoding="utf-8") as f:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
                print(f"[{mid}] {r['case']} rate={r.get('rate', r.get('json_ok'))} "
                      f"lat={r['latency']}s", flush=True)
            except Exception as e:  # noqa: BLE001 — 失败如实记录续跑
                with open(OUT, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"model": mid, "case": f"ERR#{i}",
                                        "error": str(e)[:200]}) + "\n")
                print(f"[{mid}] case#{i} ERR {str(e)[:80]}", flush=True)
    print("ALL DONE", flush=True)


if __name__ == "__main__":
    main()
