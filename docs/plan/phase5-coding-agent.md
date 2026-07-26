# Phase 5: Coding Agent 详细设计

> 文件名: `docs/plan/phase5-coding-agent.md`
> 目标包: `topoone/coder/`
> 位置: `next/backend/topoone/coder/`
> 依赖: Phase 1 `core/` + Phase 2 `tools/` + Phase 3 `llm/` + Phase 4 `agent/` + `knowledge/`
> 代码量: 新建约 1800 行

---

## 目录

1. [设计目标与原则](#1-设计目标与原则)
2. [包结构总览](#2-包结构总览)
3. [逐文件规格](#3-逐文件规格)
4. [适配器设计](#4-适配器设计)
5. [模块依赖关系图](#5-模块依赖关系图)
6. [测试规划](#6-测试规划)
7. [验证清单](#7-验证清单)

---

## 1. 设计目标与原则

### 目标

1. **需求理解**: 将自然语言需求解析为结构化任务描述
2. **精确上下文**: 从知识库 + 项目分析结果构建精确上下文 (文件列表、接口签名、约束)
3. **多适配器**: 支持 opencode / cline / codex / qwen-code，各自独立维护对话上下文
4. **结果审查**: 对第三方 Agent 返回的 diff 做自动审查 + 测试验证

### 原则

| 原则 | 说明 |
|------|------|
| **Adapter 隔离** | 每个第三方 Agent 实现独立 adapter，通过 `BaseCodingAdapter` 统一接口调用 |
| **上下文精确** | 只包含需求涉及的文件/符号/接口，不发送整个项目 |
| **规约先行** | 生成 `.spec.md` 规约文件，第三方 Agent 读取执行 |
| **结果可审查** | 返回的代码变更必须经过 diff 审查 + 测试验证 |

---

## 2. 包结构总览

```
topoone/coder/
├── __init__.py                    # 导出 CoderOrchestrator
├── orchestrator.py                # 协调器: 需求→上下文→分派→审查
├── parser.py                      # 自然语言需求解析
├── context.py                     # 上下文装配 (从知识库 + 项目分析提取)
├── spec_builder.py                # 规约描述生成 (.spec.md)
├── workspace.py                   # 临时工作区管理
├── reviewer.py                    # diff 审查 + 测试验证
│
└── adapters/                      # 第三方 Agent 适配器
    ├── __init__.py
    ├── base.py                    # BaseCodingAdapter 抽象
    ├── opencode.py                # opencode CLI 适配
    ├── cline.py                   # cline 适配
    ├── codex.py                   # codex API 适配
    └── qwen_code.py               # qwen-code API 适配
```

---

## 3. 逐文件规格

### 3.1 `coder/__init__.py`

```python
"""Coding Agent - 需求理解 → 精确上下文 → 第三方 agent 调用 → 结果审查"""
from .orchestrator import CoderOrchestrator, CodingTask, CodingResult
from .adapters.base import BaseCodingAdapter, CodingContext
```

---

### 3.2 `coder/orchestrator.py`

**新建**: Coding Agent 核心协调器

**数据类**:

```python
@dataclass
class CodingTask:
    """编码任务"""
    id: str
    requirement: str                   # 原始需求
    parsed: ParsedRequirement | None = None  # 解析后的结构化需求
    spec: str | None = None           # 生成的规约
    context: CodingContext | None = None  # 精确上下文
    status: str = "pending"           # pending | running | completed | failed
    result: CodingResult | None = None
    error: str = ""
    created_at: float = 0.0

@dataclass
class CodingResult:
    """编码结果"""
    success: bool
    diff: str = ""                    # git diff 格式
    summary: str = ""                 # 变更摘要
    files_changed: list[str] = field(default_factory=list)
    review_result: ReviewResult | None = None
    adapter_name: str = ""

@dataclass
class ReviewResult:
    """审查结果"""
    passed: bool
    issues: list[str] = field(default_factory=list)
    test_results: dict = field(default_factory=dict)  # {test_name: passed/failed}
    score: float = 0.0                # 0.0 ~ 1.0
```

**类**: `CoderOrchestrator`

```python
class CoderOrchestrator:
    """编码协调器 - 需求→上下文→分派→审查"""

    def __init__(self, multi_db: MultiDBManager, llm_service=None,
                 knowledge_service=None):
        """
        multi_db:         MultiDBManager
        llm_service:      LLMService (用于需求解析)
        knowledge_service: KnowledgeService (用于上下文检索)
        """

    # ─── 核心流程 ───

    async def run(self, requirement: str, project_id: str,
                  adapter_name: str = "opencode",
                  task_id: str | None = None) -> CodingResult:
        """
        完整流程:
        1. parser.parse(requirement) → ParsedRequirement
        2. context.build(parsed, project_id) → CodingContext
        3. spec_builder.build(parsed, context) → spec_str
        4. adapter = self._get_adapter(adapter_name)
        5. adapter.invoke(context, spec_str) → CodingResult
        6. reviewer.review(result) → 审查
        7. 返回最终结果
        """

    # ─── 多轮对话 ───

    async def continue_(self, task_id: str, feedback: str) -> CodingResult:
        """多轮推进: adapter.continue_(session_id, feedback)"""

    # ─── 任务管理 ───

    def get_status(self, task_id: str) -> CodingTask | None: ...
    def cancel(self, task_id: str): ...
    def list_tasks(self, project_id: str) -> list[CodingTask]: ...

    # ─── 适配器管理 ───

    def register_adapter(self, name: str, adapter: "BaseCodingAdapter"): ...
    def get_adapter(self, name: str) -> "BaseCodingAdapter": ...
    def list_adapters(self) -> list[str]: ...

    # ─── 注册到 ZMQServer ───

    def register(self, server: "ZMQServer"):
        """注册 coder.* RPC"""
```

**流程详细**:

```
用户: "给 userService.ts 添加登出功能"

    1. parser.parse()
       → 意图: add_feature
       → 实体: ["userService.ts"]
       → 动作: "添加登出功能"
       → 文件: ["src/services/userService.ts"]

    2. context.build()
       → 从 knowledge/ 检索相关文档
       → 从 core/analysis 获取 userService.ts 的
          依赖、调用者、接口签名、当前方法列表
       → 生成 CodingContext

    3. spec_builder.build()
       → .spec.md:
           # 任务: 给 userService.ts 添加登出功能
           ## 涉及文件
           - src/services/userService.ts (修改)
           - src/types/auth.ts (可能需修改)
           ## 现有接口
           - login(username, password) → TokenResponse
           - refreshToken(token) → TokenResponse
           ## 要求
           - 添加 logout() 方法
           - 调用 /api/auth/logout
           - 清除本地 token

    4. adapter.invoke(context, spec)
       → opencode: 写入 AGENTS.md + 执行 opencode
       → cline:    写入 instructions + 调用 cline API
       → codex:    prompt → codex API

    5. reviewer.review(result)
       → 检查 diff 语法正确
       → 运行项目测试
       → 检查是否满足 spec 要求
```

**依赖**: `coder/parser.py`, `coder/context.py`, `coder/spec_builder.py`, `coder/adapters/*`, `coder/reviewer.py`, `coder/workspace.py`

---

### 3.3 `coder/parser.py`

**新建**: 自然语言需求解析

```python
from dataclasses import dataclass, field

@dataclass
class ParsedRequirement:
    """解析后的需求"""
    intent: str                        # add_feature | fix_bug | refactor | optimize | test
    files: list[str] = field(default_factory=list)     # 涉及的文件路径
    symbols: list[str] = field(default_factory=list)   # 涉及的符号
    description: str = ""              # 原始描述
    constraints: list[str] = field(default_factory=list)  # 约束条件
    language: str = "zh"               # 语言

class RequirementParser:
    """需求解析器 - 从自然语言提取结构化信息"""

    def __init__(self, llm_service=None):
        """llm_service: 可选 LLMService (用于复杂语义解析)"""

    def parse(self, text: str, project_id: str = "") -> ParsedRequirement:
        """
        解析需求:
        1. 规则匹配 (关键词 + 正则)
        2. 若无法匹配 → LLM 辅助解析
        3. 从项目文件树匹配实体
        """

    def _rule_based_parse(self, text: str) -> ParsedRequirement | None:
        """基于规则快速解析 (文件路径匹配 + 意图关键词)"""

    async def _llm_parse(self, text: str) -> ParsedRequirement:
        """基于 LLM 的深度解析"""
```

**依赖**: `core/project/` (文件树), Phase 3 `llm/service.py` (可选)

---

### 3.4 `coder/context.py`

**新建**: 精确上下文装配

```python
from dataclasses import dataclass
from pathlib import Path

@dataclass
class CodingContext:
    """编码上下文 - 精确到文件/符号级别"""
    project_id: str
    project_root: str
    target_files: list[str]            # 主要涉及文件
    related_files: list[str]           # 关联文件 (调用者/被调者)
    symbols: list[dict]                # 涉及符号 (名称/类型/签名/位置)
    dependencies: list[dict]           # 外部依赖
    tech_stack: dict                   # 技术栈
    knowledge_docs: list[dict] = field(default_factory=list)  # 相关知识库文档
    constraints: list[str] = field(default_factory=list)      # 约束
    spec: str = ""                     # 规约文件路径

class ContextBuilder:
    """上下文构建器 - 从知识库 + 项目分析提取精确上下文"""

    def __init__(self, multi_db, knowledge_service=None):
        self.multi_db = multi_db
        self.knowledge = knowledge_service

    def build(self, parsed: ParsedRequirement) -> CodingContext:
        """
        构建上下文:
        1. 解析目标文件路径
        2. 从 core/store/analysis_store 获取符号/依赖
        3. 从 core/analysis/community 获取文件间关系
        4. 从 knowledge 检索相关文档
        5. 过滤: 只保留与需求相关的信息
        """

    def _resolve_files(self, files: list[str], project_root: str) -> list[str]:
        """解析文件路径 (支持模糊匹配)"""

    def _get_symbols(self, files: list[str], project_id: str) -> list[dict]:
        """获取文件的导出符号 + 签名"""

    def _get_dependencies(self, files: list[str], project_id: str) -> list[dict]:
        """获取文件的外部依赖"""

    def _search_knowledge(self, query: str, project_id: str) -> list[dict]:
        """从知识库检索相关文档"""
```

**依赖**: Phase 1 `core/store/analysis_store.py`, `core/analysis/community.py`; Phase 4 `knowledge/service.py`

---

### 3.5 `coder/spec_builder.py`

**新建**: 规约描述生成

```python
class SpecBuilder:
    """规约构建器 - 生成 .spec.md 规约文件"""

    def build(self, context: CodingContext, parsed: ParsedRequirement) -> str:
        """
        生成规约内容 (Markdown):
        # 编码任务
        ## 需求描述
        ## 涉及文件
        ## 现有接口 (签名)
        ## 技术约束
        ## 测试要求
        ## 完成标准
        """

    def save(self, spec: str, task_dir: str) -> str:
        """保存到 task_dir/spec.md, 返回路径"""
```

**依赖**: 无

---

### 3.6 `coder/workspace.py`

**新建**: 临时工作区管理

```python
import tempfile
import os
import shutil
from pathlib import Path

class TaskWorkspace:
    """编码任务工作区 - 隔离的临时目录"""

    def __init__(self, base_dir: str | None = None):
        """
        base_dir: 工作区根目录，默认 /tmp/topoone-coder/
        """
        self.base_dir = Path(base_dir or "/tmp/topoone-coder")
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def create(self, task_id: str) -> Path:
        """创建任务目录: {base_dir}/{task_id}/"""
        path = self.base_dir / task_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def cleanup(self, task_id: str):
        """清理任务目录"""
        path = self.base_dir / task_id
        if path.exists():
            shutil.rmtree(path)

    def cleanup_old(self, max_age_hours: int = 24):
        """清理超过 max_age_hours 的目录"""
```

---

### 3.7 `coder/reviewer.py`

**新建**: diff 审查 + 测试验证

```python
from dataclasses import dataclass

@dataclass
class ReviewResult:
    passed: bool
    issues: list[str] = field(default_factory=list)
    test_results: dict = field(default_factory=dict)
    score: float = 0.0

class CodeReviewer:
    """代码审查器 - diff 检查 + 测试验证"""

    def __init__(self, multi_db=None):
        self.multi_db = multi_db

    def review(self, diff: str, spec: str) -> ReviewResult:
        """
        审查步骤:
        1. 解析 diff 格式
        2. 检查是否有语法错误
        3. 对比 spec 检查完成度
        4. 检查是否引入安全漏洞
        5. 运行受影响文件的测试
        """

    def _check_diff_format(self, diff: str) -> list[str]:
        """检查 diff 格式是否合法"""

    def _check_spec_compliance(self, diff: str, spec: str) -> list[str]:
        """检查是否满足 spec 要求"""

    def _check_security(self, diff: str) -> list[str]:
        """安全扫描 (注入、路径穿越等)"""

    async def run_tests(self, project_root: str, files: list[str]) -> dict:
        """运行涉及文件的测试, 返回 {test_name: passed/failed}"""

    def calculate_score(self, issues: list[str], test_results: dict) -> float:
        """综合评分 0.0~1.0"""
```

---

### 3.8 `coder/adapters/base.py`

**新建**: 第三方 Coding Agent 适配器抽象

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class AdapterCapability:
    """适配器能力描述"""
    supports_multi_turn: bool = False     # 是否支持多轮对话
    max_context_window: int = 0           # 最大上下文窗口 (字符)
    supports_tools: bool = False          # 是否支持工具调用
    requires_workspace: bool = True       # 是否需要工作区

@dataclass
class CodingContext:
    """编码上下文 - 传递给第三方 Agent"""
    project_root: str
    target_files: list[str]
    spec_path: str                       # 规约文件路径
    workspace_dir: str                   # 工作区目录
    extra: dict = field(default_factory=dict)

class BaseCodingAdapter(ABC):
    """第三方编码 Agent 适配器基类"""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def capabilities(self) -> AdapterCapability: ...

    @abstractmethod
    async def invoke(self, context: CodingContext) -> CodingResult:
        """
        首次/单次调用
        - context: 编码上下文
        - 返回: CodingResult
        """

    @abstractmethod
    async def continue_(self, session_id: str, feedback: str) -> CodingResult:
        """
        多轮对话推进
        - session_id: 上次调用返回的会话 ID
        - feedback: 用户反馈或修改要求
        - 返回: CodingResult
        """

    @abstractmethod
    async def cancel(self, session_id: str):
        """取消任务"""

    async def get_status(self, session_id: str) -> str:
        """查询任务状态 (可选实现)"""
        return "unknown"

    async def get_result(self, session_id: str) -> CodingResult | None:
        """获取最终结果 (可选实现)"""
        return None
```

---

### 3.9 `coder/adapters/opencode.py`

**新建**: opencode CLI 适配

```python
class OpenCodeAdapter(BaseCodingAdapter):
    """opencode CLI 适配器 - 通过命令行调用 opencode"""

    @property
    def name(self) -> str: return "opencode"

    @property
    def capabilities(self) -> AdapterCapability:
        return AdapterCapability(
            supports_multi_turn=True,
            max_context_window=128000,
            supports_tools=False,
            requires_workspace=True,
        )

    async def invoke(self, context: CodingContext) -> CodingResult:
        """
        1. 在工作区写入 AGENTS.md (包含 spec 内容)
        2. 写入 .clinerules 或规则文件
        3. 执行: opencode --model xxx --task spec.md
        4. 捕获 stdout + 获取 git diff
        5. 返回 CodingResult
        """

    async def continue_(self, session_id: str, feedback: str) -> CodingResult:
        """
        多轮对话: 写入 feedback 到文件, 再次调用 opencode
        """
```

---

### 3.10 `coder/adapters/cline.py`

**新建**: cline 适配器

```python
class ClineAdapter(BaseCodingAdapter):
    """cline 适配器 - 通过 cline API / VSCode 扩展"""

    @property
    def name(self) -> str: return "cline"

    @property
    def capabilities(self) -> AdapterCapability:
        return AdapterCapability(
            supports_multi_turn=True,
            max_context_window=64000,
            supports_tools=True,
            requires_workspace=False,
        )

    async def invoke(self, context: CodingContext) -> CodingResult:
        """
        1. 生成 custom instruction (含 spec)
        2. 通过 cline API 发送请求
        3. 流式接收结果 (或轮询)
        4. 解析最终 diff
        """
```

---

### 3.11 `coder/adapters/codex.py`

**新建**: codex CLI / API 适配器

```python
class CodexAdapter(BaseCodingAdapter):
    """codex CLI / API 适配器"""

    @property
    def name(self) -> str: return "codex"

    @property
    def capabilities(self) -> AdapterCapability:
        return AdapterCapability(
            supports_multi_turn=True,
            max_context_window=100000,
            supports_tools=False,
            requires_workspace=True,
        )

    async def invoke(self, context: CodingContext) -> CodingResult:
        """
        1. 通过 codex CLI 调用 (subprocess)
        2. 或通过 codex API (HTTP)
        3. 收集输出 diff
        """
```

---

### 3.12 `coder/adapters/qwen_code.py`

**新建**: qwen-code API 适配器

```python
class QwenCodeAdapter(BaseCodingAdapter):
    """qwen-code API 适配器"""

    @property
    def name(self) -> str: return "qwen-code"

    @property
    def capabilities(self) -> AdapterCapability:
        return AdapterCapability(
            supports_multi_turn=True,
            max_context_window=32000,
            supports_tools=False,
            requires_workspace=False,
        )

    async def invoke(self, context: CodingContext) -> CodingResult:
        """
        1. 构建 prompt (含 spec + 上下文)
        2. 通过 qwen-code API 发送
        3. 解析返回的代码变更
        """
```

---

## 4. 适配器设计

### 4.1 接口统一

```
BaseCodingAdapter
│
├── name() → str                    # "opencode" | "cline" | "codex" | "qwen-code"
├── capabilities() → AdapterCapability
│
├── invoke(context) → CodingResult       # 首次/单次调用
├── continue_(session_id, feedback) → CodingResult  # 多轮推进
├── cancel(session_id)                     # 取消
├── get_status(session_id) → str           # 查询状态
└── get_result(session_id) → CodingResult  # 获取结果
```

### 4.2 调用模式对比

| 适配器 | 通信方式 | 多轮 | 上下文保持 | 核心差异 |
|--------|----------|------|-----------|----------|
| opencode | CLI subprocess | 是 | 本地文件 AGENTS.md | 通过规则文件控制行为 |
| cline | API / VSCode | 是 | 服务端 session | 支持工具调用, 可自主探索 |
| codex | CLI / API | 是 | 本地 workspace | 通过 prompt 描述任务 |
| qwen-code | API | 是 | 服务端 session | 较小的上下文窗口 |

### 4.3 配置存储

```json
{
  "coder": {
    "default_adapter": "opencode",
    "adapters": {
      "opencode": {
        "command": "opencode",
        "args": ["--model", "deepseek-v4"],
        "enabled": true
      },
      "cline": {
        "api_key": "",
        "api_base": "",
        "model": "claude-opus-4",
        "enabled": false
      }
    }
  }
}
```

配置存储在 `app_config` 表中，key=`coder_config`。

---

## 5. 模块依赖关系图

```
coder/adapters/base.py           ← 无依赖
coder/adapters/opencode.py       → base.py, subprocess
coder/adapters/cline.py          → base.py, requests
coder/adapters/codex.py          → base.py, subprocess/requests
coder/adapters/qwen_code.py      → base.py, requests

coder/parser.py                  → core/project/(文件树), llm/service.py (可选)
coder/context.py                 → core/store/analysis_store.py
                                   core/analysis/community.py
                                   knowledge/service.py
coder/spec_builder.py            ← 无依赖
coder/workspace.py               ← 无依赖

coder/reviewer.py                → core/db/ (测试结果记录)

coder/orchestrator.py            → parser, context, spec_builder,
                                   adapters/*, reviewer, workspace
                                   core/db/manager.py (任务持久化)
                                   transport/server.py (RPC 注册)
```

---

## 6. 测试规划

```
tests/coder/
├── test_parser.py                # 需求解析 (规则 + LLM mock)
├── test_context.py               # 上下文构建 (mock analysis_store)
├── test_spec_builder.py          # 规约生成
├── test_workspace.py             # 工作区创建/清理
├── test_reviewer.py              # diff 审查 + 安全扫描
├── test_orchestrator.py          # 完整流程 (mock adapters)
└── adapters/
    ├── test_base.py              # 基类接口
    ├── test_opencode.py          # subprocess mock
    ├── test_cline.py             # HTTP mock
    └── test_codex.py             # HTTP mock
```

### 关键测试

```python
async def test_full_pipeline():
    """完整流程: 需求→解析→上下文→规约→adapter mock→审查"""
    orch = CoderOrchestrator(mock_db, mock_llm, mock_knowledge)
    orch.register_adapter("mock", MockAdapter())
    result = await orch.run("给 userService.ts 添加登出功能", "proj-1", adapter_name="mock")
    assert result.success
    assert len(result.files_changed) > 0

def test_requirement_parse():
    parser = RequirementParser()
    parsed = parser.parse("给 userService.ts 添加登出功能")
    assert parsed.intent == "add_feature"
    assert "userService.ts" in parsed.files

def test_spec_generation():
    builder = SpecBuilder()
    context = CodingContext(project_id="p1", ...)
    spec = builder.build(context, parsed)
    assert "# 编码任务" in spec
    assert "userService.ts" in spec
```

---

## 7. 验证清单

```bash
# 1. 包导入
python -c "
from topoone.coder import CoderOrchestrator
from topoone.coder.adapters import BaseCodingAdapter, CodingContext
from topoone.coder.parser import RequirementParser
from topoone.coder.spec_builder import SpecBuilder
from topoone.coder.reviewer import CodeReviewer
print('coder OK')
"

# 2. 适配器注册
python -c "
from topoone.coder.adapters import OpenCodeAdapter, ClineAdapter, CodexAdapter
from topoone.coder import CoderOrchestrator
orch = CoderOrchestrator(None)
orch.register_adapter('opencode', OpenCodeAdapter())
orch.register_adapter('cline', ClineAdapter())
print(f'Adapters: {orch.list_adapters()}')
"

# 3. 全部测试
cd next/backend && python -m pytest tests/coder/ -v
```

**Phase 5 完成标志**:
1. 需求解析支持规则 + LLM 两种模式
2. 上下文装配可精确提取目标文件的符号/依赖/关系
3. 规约生成包含完整任务描述
4. 至少一个 adapter (opencode) 可端到端运行
5. diff 审查包含格式检查 + spec 合规 + 安全检查
6. 全部 pytest 测试通过
