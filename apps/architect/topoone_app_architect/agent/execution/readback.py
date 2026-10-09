"""解读回环(readback handshake, 意图空间一期 D4, 裁决 2026-10-09)——零 runner 协议改动。

防语义污染的最后闸口: 下发指令附「先解读后开工」段, 执行器首回合按自身
理解输出解读(目标复述/代码坐标/计划要点/冲突点/疑问)并主动等待输入
(input_required); architect 在 input_required 到达时规则校验——

裁决方式(用户决策): 规则可判的自动裁决(代码坐标对账/验收点覆盖比对),
语义偏差以建议呈现、用户终裁(经既有输入通道放行/纠偏, 一次循环不往复)。
开启策略: 安全等级 high-stakes 默认开, 其余默认关; task.readback
("on"|"off")显式覆盖(挡位默认之上的手动开关)。
"""
from __future__ import annotations

import re
from typing import Dict, List

# 指令注入段: 要求执行器先输出「我的理解」再等确认(与冲突约定总则呼应——
# 描述与代码冲突以代码为准, 冲突点在解读中明确指出)
READBACK_INSTRUCTION = (
    "\n\n## 开工前解读（readback）\n"
    "正式动手前，先输出你对本任务的**解读**，然后停下来等待确认（不要开始修改代码）：\n"
    "1. **目标复述**：用你自己的话说明这个任务要达成什么；\n"
    "2. **涉及代码**：列出你定位到的具体文件/符号（代码坐标）；\n"
    "3. **计划要点**：打算分几步做、每步做什么；\n"
    "4. **冲突点**：上文描述与代码事实不一致之处（如有——以代码为准并在此指出）；\n"
    "5. **疑问**：需要人澄清的问题（如有）。\n"
    "输出解读后即等待输入；得到确认（如「理解正确，开工」）后再开始执行，"
    "有偏差则按纠正意见调整解读后开工。")

# 任务行显式覆盖挡位默认: "on" | "off" | ""(空=按挡位)
_READBACK_ON = "on"
_READBACK_OFF = "off"


def readback_enabled(task: dict) -> bool:
    """开启判定(单源): task.readback 显式覆盖 > 安全等级挡位默认。"""
    task = task or {}
    flag = str(task.get("readback") or "").strip().lower()
    if flag == _READBACK_ON:
        return True
    if flag == _READBACK_OFF:
        return False
    return str(task.get("safetyClass") or "").strip().lower() == "high-stakes"


# ── 规则校验(纯函数): 代码坐标对账 + 验收点覆盖 ─────────────────────────────

_PATH_RE = re.compile(r"(?:[\w.\-]+/)*[\w.\-]+\.[A-Za-z]{1,6}\b")
_CODE_EXT = {".ts", ".tsx", ".js", ".jsx", ".vue", ".py", ".go", ".rs",
             ".java", ".kt", ".c", ".h", ".cpp", ".cs", ".rb", ".php",
             ".swift", ".sql", ".json", ".yaml", ".yml", ".toml", ".css",
             ".scss", ".html", ".sh", ".md"}


def _extract_paths(text: str) -> List[str]:
    out, seen = [], set()
    for m in _PATH_RE.findall(text or ""):
        low = m.lower()
        if ("." + low.rsplit(".", 1)[-1]) not in _CODE_EXT:
            continue
        if low not in seen:
            seen.add(low)
            out.append(m)
    return out[:20]


def _tokens(text: str) -> set:
    """关键词集: ASCII 词(≥2)小写化 + 中文 2-gram(覆盖比对的粗粒度信号)。"""
    out = set()
    for m in re.findall(r"[A-Za-z0-9_\-./]+|[\u4e00-\u9fff]+", text or ""):
        if m.isascii():
            if len(m) >= 2:
                out.add(m.lower())
        else:
            out |= {m[i:i + 2] for i in range(len(m) - 1)}
    return out


def verdict_of(readback_text: str, boundary_files: List[str],
               acceptance: List[str]) -> Dict[str, object]:
    """规则校验: 解读中的代码坐标是否落在边界内 + 验收条目是否被呼应。

    - 界内判定: 相等或以边界路径(含目录前缀)开头;
    - 验收覆盖: 条目 token(去重前 8)过半出现在解读 token 集即算呼应;
    - pass = 无疑似越界 且 无未呼应验收。粗规则信号, 偏差人工终裁。
    """
    boundary = [str(f).strip().lower().rstrip("/") for f in (boundary_files or []) if f]

    def _in_scope(p: str) -> bool:
        low = p.lower()
        for b in boundary:
            if low == b or low.startswith(b + "/") or b.startswith(low + "/"):
                return True
        return False

    paths = _extract_paths(readback_text)
    out_scope = [p for p in paths if not _in_scope(p)]

    rb_tokens = _tokens(readback_text)
    missing: List[str] = []
    for acc in (acceptance or [])[:12]:
        toks = list(dict.fromkeys(_tokens(str(acc))))[:8]
        if not toks:
            continue
        hit = sum(1 for t in toks if t in rb_tokens)
        if hit * 2 < len(toks):
            missing.append(str(acc))

    return {"paths": paths, "outScope": out_scope,
            "acceptanceTotal": min(len(acceptance or []), 12),
            "missingAcceptance": missing,
            "pass": not out_scope and not missing}


def render_verdict(v: Dict[str, object]) -> str:
    """校验结果 → 落卡建议文本(附注在解读消息尾部; 用户裁决)。"""
    n_paths = len(v.get("paths") or [])
    out_scope = v.get("outScope") or []
    missing = v.get("missingAcceptance") or []
    total = int(v.get("acceptanceTotal") or 0)
    lines = ["", "---", "🔍 **解读校验（规则自动，供你裁决）**"]
    lines.append(f"- 代码坐标 {n_paths} 处，边界对账 "
                 + ("✅ 全部在界内" if not out_scope
                    else f"⚠️ 疑似越界 {len(out_scope)} 处：{', '.join(out_scope[:6])}"))
    if total:
        lines.append(f"- 验收呼应 {total - len(missing)}/{total} "
                     + ("✅" if not missing else
                        f"⚠️ 未呼应：{'；'.join(m[:3] for m in missing[:3])}"))
    lines.append("✅ 规则校验通过——可回复「理解正确，开工」放行。"
                 if v.get("pass") else
                 "⚠️ 存在上述信号——请核对后放行（回复确认）或纠偏（指出问题）。"
                 "语义层面的偏差以你的判断为准。")
    return "\n".join(lines)
