"""回合内循环检测(环节十一) — 执行器无关的事件面检测器。

问题实证(cv-173/176/179): subagent 在"改→编译→再改→同错"或反复重读文件上
无限消耗轮次, 轮次上限放大(2000)后必须靠检测器防异常浪费。

两类信号(数据面为 runner 事件流; opencode/codex 无流式事件 → 优雅降级,
仅 implement._watch_turn 的 worktree 无进展看门狗生效):

- 重复指纹: 以 usage 事件切分 LLM 轮; 连续 N 轮的 (工具序列 + 文本归一摘要)
  完全一致 → 判定循环(模型在字面重复自己)。
- 错误签名: 同一文本归一摘要在回合内累计出现 ≥M 次(非连续也计) → 判定循环
  (同一叙述/错误反复出现)。

文本归一: 小写 + 去数字 + 折叠空白——容忍 pid/时间戳/行号抖动。
判定 → (True, 原因); 由 implement._watch_turn 消费转 failed(进度已自动 commit)。
"""
from __future__ import annotations

import hashlib
import re
from typing import Dict, List, Optional, Tuple


def _norm_digest(text: str) -> str:
    """文本归一摘要: 小写+去数字+折叠空白后取 sha1 前 16 位。"""
    if not text:
        return ""
    cleaned = re.sub(r"\s+", " ", re.sub(r"\d+", "", text)).strip().lower()
    if not cleaned:
        return ""
    return hashlib.sha1(cleaned.encode("utf-8")).hexdigest()[:16]


class LoopGuard:
    """回合内循环检测器(每回合新建; 事件驱动, 纯内存零 IO)。"""

    def __init__(self, repeat_rounds: int = 3, signature_hits: int = 8,
                 min_sig_len: int = 40):
        # signature_hits=8: 重复状态话术("编译通过, 测试全绿"类)在长回合里
        # 可以合法重复多次——×5 过紧会误杀(误伤排查); ×8 已远超正常重复密度
        self._repeat_rounds = max(2, int(repeat_rounds))
        self._signature_hits = max(2, int(signature_hits))
        self._min_sig_len = int(min_sig_len)
        self._round_tools: List[str] = []
        self._round_text: List[str] = []
        self._last_fp: Optional[Tuple[str, ...]] = None
        self._fp_streak = 0
        self._sig_seen: Dict[str, int] = {}
        self._verdict: str = ""

    def reset(self) -> None:
        """新回合复位(实现侧每回合新建实例, 此方法供复用场景)。"""
        self._round_tools = []
        self._round_text = []
        self._last_fp = None
        self._fp_streak = 0
        self._sig_seen = {}
        self._verdict = ""

    def feed(self, kind: str, text: str = "", tool_name: str = ""
             ) -> Tuple[bool, str]:
        """喂入事件: kind ∈ tool|text|usage。返回 (是否循环, 原因)。

        判定后进入粘滞态(持续返回同一原因)——回合已判死, 不因后续事件翻转。
        """
        if self._verdict:
            return True, self._verdict
        if kind == "tool":
            if tool_name:
                self._round_tools.append(str(tool_name))
        elif kind == "text":
            if text:
                self._round_text.append(str(text))
                d = _norm_digest(text)
                if len((text or "").strip()) >= self._min_sig_len and d:
                    n = self._sig_seen.get(d, 0) + 1
                    self._sig_seen[d] = n
                    if n >= self._signature_hits:
                        self._verdict = (f"同一文本签名重复 {n} 次"
                                         f"(digest={d})")
                        return True, self._verdict
        elif kind == "usage":
            self._close_round()
        return (bool(self._verdict), self._verdict)

    def _close_round(self) -> None:
        """usage → 回合收口: 指纹比对 + 轮缓冲复位。

        **只统计有实质叙述的轮**(误伤修复, cv-181 实证): 指纹的证据是
        "模型在字面重复自己"——静默轮(无文本)没有这个证据, 且不同命令
        批次在工具名指纹下不可区分; 静默轮重置计数。真静默循环由
        implement 无进展看门狗(文件状态)兜底。
        """
        text_digest = _norm_digest(" ".join(self._round_text))
        fp = (tuple(self._round_tools), text_digest)
        self._round_tools = []
        self._round_text = []
        if not text_digest:
            self._last_fp = None
            self._fp_streak = 0
            return
        if fp == self._last_fp:
            self._fp_streak += 1
        else:
            self._last_fp = fp
            self._fp_streak = 1
        if self._fp_streak >= self._repeat_rounds:
            tools = ", ".join(fp[0][:6]) or "(无工具)"
            self._verdict = (f"连续 {self._fp_streak} 轮工具序列与叙述完全一致"
                             f"(指纹轮: {tools})")
