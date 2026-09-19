"""grep 门禁(R1.3/R1.4 + D12, 整体设计 §7-3) — 棘轮式白名单, 只紧不松。

① llm_sync 裸调白名单: 链 3 全量收编后仅 turns/call.py 允许调用(D12);
   M0 冻结现有调用方清单, 新增调用方即红灯。
② 挡位字面量(T0-T4): 治理单源(governance/gears.py)与既有消费文件外,
   禁止新文件散落(R1.4)。
白名单存 goldens/grep_whitelist.json(生成脚本口径一致, 2026-09-19 基线)。

Run: cd <repo> && python -m pytest apps/architect/tests/test_grep_gates.py -q
"""
import json
import os
import re
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

PKG = os.path.join(_repo, "apps/architect/topoone_app_architect")
WHITELIST_PATH = os.path.join(os.path.dirname(__file__), "goldens",
                              "grep_whitelist.json")

with open(WHITELIST_PATH, encoding="utf-8") as f:
    _WL = json.load(f)
LLM_SYNC_WHITELIST = set(_WL["llm_sync_callers"])
TIER_FILE_WHITELIST = set(_WL["tier_literal_files"])

# 白名单内允许的挡位字面量文件(棘轮只增红灯不增白名单; 清理时收缩此集合)
_TIER_HARD_ALLOWED = {
    "agent/governance/gears.py",        # 策略表单源
    "agent/cognition/model_profile.py",  # A 轴探测刻度
}


def _py_sources():
    for sub in ("agent", "arch_routes"):
        root = os.path.join(PKG, sub)
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for fn in sorted(filenames):
                if fn.endswith(".py"):
                    full = os.path.join(dirpath, fn)
                    rel = os.path.relpath(full, PKG).replace(os.sep, "/")
                    with open(full, encoding="utf-8") as f:
                        yield rel, f.read()


def test_llm_sync_no_new_callers():
    """D12 棘轮: llm_sync 调用方不得新增(收编后白名单收缩至 turns/call.py)。"""
    offenders = []
    for rel, src in _py_sources():
        if "def llm_sync" in src:            # 定义处
            continue
        if re.search(r"\bllm_sync\s*\(", src) and rel not in LLM_SYNC_WHITELIST:
            offenders.append(rel)
    assert not offenders, (
        f"llm_sync 新增调用方(走补偿管线 turns.call, 勿裸调): {offenders}")


def test_tier_literals_no_new_files():
    """R1.4 棘轮: 挡位字面量不得散落新文件(挡位语义经 GearPolicy 表达)。"""
    offenders = []
    for rel, src in _py_sources():
        if rel in _TIER_HARD_ALLOWED:
            continue
        if re.search(r"\bT[0-4]\b", src) and rel not in TIER_FILE_WHITELIST:
            offenders.append(rel)
    assert not offenders, f"挡位字面量散落新文件(改经 GearPolicy/CompensationCtx): {offenders}"


def test_whitelist_files_still_exist():
    """白名单有效性: 被收编清理的文件应同步从 goldens 白名单移除。"""
    all_files = {rel for rel, _ in _py_sources()}
    stale = [p for p in (LLM_SYNC_WHITELIST | TIER_FILE_WHITELIST)
             if p not in all_files]
    assert not stale, f"白名单含已不存在文件(请收缩白名单): {stale}"
