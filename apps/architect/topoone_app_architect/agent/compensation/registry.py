"""Provider 注册表(L1) — 补偿提供方单源登记 + 消费清单自省(R1.2/R1.3 门禁依据)。

M0 骨架: 注册表与自省机制, 内置 Provider 尚未收编(M1 起逐批)。
Provider 协议:
    name: str                          # 唯一登记名
    purposes: frozenset[Purpose]       # 服务目的集合(空集 = 全目的)
    consumes: frozenset[str]           # 声明消费的 GearPolicy 字段(R1.2 消费清单)
    assemble(ctx, prompt) -> None      # 装配时刻: 贡献 PromptPiece / RunParams
    conclude(ctx, output) -> Verdict|None   # 收尾时刻: 契约解析 / 门禁 / 重试判定
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Protocol, runtime_checkable

from .ctx import CompensationCtx, Purpose


@runtime_checkable
class CompensationProvider(Protocol):
    """补偿提供方协议(整体设计 §3.2)。"""

    name: str
    purposes: frozenset
    consumes: frozenset

    def assemble(self, ctx: CompensationCtx, prompt: Any) -> None: ...

    def conclude(self, ctx: CompensationCtx, output: Any) -> Optional[Any]: ...


@dataclass
class _Entry:
    provider: CompensationProvider
    priority: int


class ProviderRegistry:
    """按 (priority, name) 升序应用的提供方注册表; 消费清单可自省。"""

    def __init__(self) -> None:
        self._entries: List[_Entry] = []

    def register(self, provider: CompensationProvider, priority: int = 50) -> None:
        names = [e.provider.name for e in self._entries]
        if provider.name in names:
            raise ValueError(f"Provider 重复登记: {provider.name}")
        self._entries.append(_Entry(provider=provider, priority=int(priority)))
        self._entries.sort(key=lambda e: (e.priority, e.provider.name))

    def providers(self, purpose: Optional[Purpose] = None) -> List[CompensationProvider]:
        """按优先序返回; 指定 purpose 时过滤(purposes 空集 = 全目的)。"""
        out: List[CompensationProvider] = []
        for e in self._entries:
            p = e.provider.purposes
            if purpose is None or not p or purpose in p:
                out.append(e.provider)
        return out

    def consumption_map(self) -> Dict[str, List[str]]:
        """GearPolicy 字段 → 消费该字段的 Provider 名清单(门禁自省口)。"""
        mapping: Dict[str, List[str]] = {}
        for e in self._entries:
            for f in getattr(e.provider, "consumes", frozenset()):
                mapping.setdefault(str(f), []).append(e.provider.name)
        return mapping

    def __len__(self) -> int:
        return len(self._entries)


GLOBAL_REGISTRY = ProviderRegistry()
"""进程级默认注册表(M1 收编时内置 Provider 登记于此; 测试用独立实例)。"""
