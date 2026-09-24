"""K1 知识资产格式版本化 — 表级 schema_version + 只追加迁移链。

设计(用户裁决 2026-09-17, dsh 机制可抄/存储引擎不抄):
- **双域对象**: 持久知识四表 arch_semantic_assets / arch_glossary /
  arch_context_units / arch_docs(登记文档 docs/architect/kb-schema-versions.md);
- **读时惰性迁移**: 旧行读时经链补齐/变换(内存态), 不批量刷库——下次写时落新版本;
- **只追加**: 每个版本步恰注册一次迁移(vN→vN+1 一组函数), SCHEMA_VERSIONS
  bump 前必须先注册; 缺口/重复 = RuntimeError(catalog 静态校验原则: 拒绝缺口);
- **变更纪律**: meta/refs 等自由 JSON 键结构变更 = bump SCHEMA_VERSIONS +
  register_migration + 快照测试(登记文档逐条记录);
- 未登记表 apply_migrations 为恒等(模块级挂钩安全, 多表 store 共享无需区分)。

迁移函数操作对象为 **API 形状行**(camelCase, JSON 已解码)——由 store 层
_row_to_api 之后调用; 函数就地修改 row 并返回 None(统一 fold 语义)。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List

# 持久知识四表的当前版本(唯一手写权威; 发布记录见登记文档)
SCHEMA_VERSIONS: Dict[str, int] = {
    "arch_semantic_assets": 1,
    "arch_glossary": 1,
    "arch_context_units": 1,
    "arch_docs": 1,
}

# {table: {from_version: [fn(row) -> None]}} —— 只追加, 禁改写已注册条目
_MIGRATIONS: Dict[str, Dict[int, List[Callable[[Dict[str, Any]], None]]]] = {}


def register_migration(table: str, from_version: int,
                       *fns: Callable[[Dict[str, Any]], None]) -> None:
    """注册 vN→vN+1 迁移(只追加; 重复注册同版本步 = 开发错误, 拒绝)。"""
    steps = _MIGRATIONS.setdefault(table, {})
    if from_version in steps:
        raise RuntimeError(
            f"迁移链冲突: {table} v{from_version}→v{from_version + 1} 已注册")
    steps[from_version] = list(fns)


def table_version(table: str) -> int:
    """表当前版本(未登记表 = 1, 恒等域)。"""
    return SCHEMA_VERSIONS.get(table, 1)


def apply_migrations(table: str, row: Dict[str, Any]) -> Dict[str, Any]:
    """读时惰性迁移: row.schemaVersion < 表版本 → 依链应用(内存态, 不写库)。

    缺步(注册缺口)即 raise——迁移链完整性不依赖运行时配置。
    """
    target = SCHEMA_VERSIONS.get(table)
    if target is None:
        return row  # 未登记表: 恒等
    v = int(row.get("schemaVersion") or 1)
    steps = _MIGRATIONS.get(table, {})
    while v < target:
        chain = steps.get(v)
        if chain is None:
            raise RuntimeError(
                f"迁移链缺口: {table} v{v}→v{v + 1} 未注册"
                f"(bump SCHEMA_VERSIONS 前必须 register_migration)")
        for fn in chain:
            fn(row)
        v += 1
    row["schemaVersion"] = v
    return row
