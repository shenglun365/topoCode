# ⚠️ DEPRECATED — 已迁移至主项目

**迁移日期**: 2026-05-11

原 transplant-animation 的 TopoScript 动画引擎代码已完整迁移到:

```
src/lib/topo-animation/
```

## 迁移内容

| 原始模块 | 目标位置 |
|---------|---------|
| `src/core/` | `src/lib/topo-animation/core/` |
| `src/compiler/` | `src/lib/topo-animation/compiler/` |
| `src/renderer/` | `src/lib/topo-animation/renderer/` |
| `src/animator/` | `src/lib/topo-animation/animator/` |
| `src/runtime/` | `src/lib/topo-animation/runtime/` |
| `src/export/` | `src/lib/topo-animation/export/` |
| `src/utils/` | `src/lib/topo-animation/utils/` |
| `src/index.ts` | `src/lib/topo-animation/index.ts` |

## 使用方式

```ts
import { compile, createAnimationEngine } from '@topo-animation';
```

## 关键变更

1. PixiJS 适配: v7 → v8 (主项目统一 v8)
2. 路径别名: `@topo-animation/*` → `src/lib/topo-animation/*`
3. 类型修复: 已消除所有 TS 编译错误

## 保留原因

此目录保留作为 git 历史参考。所有新开发请在 `src/lib/topo-animation/` 中进行。
