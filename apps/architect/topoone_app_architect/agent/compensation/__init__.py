"""compensation — architect agent 内核 L1 补偿包(整体设计 §3)。

M0 骨架: 词表/载体/注册表/管线机制, 零行为接线(D3 收编等价前提)。
收编排期见 docs/architect/agent-capability-design-2609.md §9。
"""
from .carriers import (ArtifactGate, GateResult, OutputContract, PromptPiece,
                       RunParams, RetryPolicy)
from .ctx import (PROBE_DIMENSION, PURPOSE_WEAK_SCORE, Axis, BudgetParams,
                  CapabilityScores, CompensationCtx, ProbeFlags, Purpose,
                  resolve_ctx)
from .pipeline import (AssembledPrompt, TurnOutput, Verdict, assemble,
                       conclude, run_with_retry)
from .registry import GLOBAL_REGISTRY, CompensationProvider, ProviderRegistry

__all__ = [
    "ArtifactGate", "GateResult", "OutputContract", "PromptPiece", "RunParams",
    "RetryPolicy", "PROBE_DIMENSION", "PURPOSE_WEAK_SCORE", "Axis",
    "BudgetParams", "CapabilityScores", "CompensationCtx", "ProbeFlags",
    "Purpose", "resolve_ctx", "AssembledPrompt", "TurnOutput", "Verdict",
    "assemble", "conclude", "run_with_retry", "GLOBAL_REGISTRY",
    "CompensationProvider", "ProviderRegistry",
]
