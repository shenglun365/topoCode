export default {
  aiAssistant: {
    title: 'AI 助手',
    emptyHint: '有什么代码问题需要帮忙？',
    placeholder: '输入问题... (Shift+Enter 换行)',
    you: '你',
    ai: 'AI',
    commands: {
      help: '/帮助',
    },
    context: {
      codeAnalysis: '代码解析',
      architectureAnalysis: '架构分析',
      freeChat: '自由对话',
      project: '项目「{name}」',
      task: '任务「{name}」',
      currentContext: '当前上下文：{parts}',
    },
    pipeline: {
      completed: '流水线执行完成',
      firstSuccess: '首次成功: {completed} 步',
      retrySuccess: '重试后成功:（累计重试 {retries} 次）',
      executionFailed: '执行失败:（内容未写入）',
      retryCount: '（重试 {count} 次）',
      retryHint: '使用 /retry 命令重新执行（默认跳过成功任务，--force 强制覆盖）。',
      forceOverwriteAll: '（强制覆盖所有）',
      skipCompleted: '（跳过已完成）',
      started: '流水线已启动{hint}。顺序执行：项目摘要 → 预摘要 P0→P1→P2 → 组件分析 L0→L5 → 整体架构分析。请到「任务」面板查看进度。',
    },
    errors: {
      noActiveTask: '未找到激活的任务。',
      noCommunityList: '社区列表尚未加载，请先打开左侧结构图。',
      noMatchingCommunity: '未找到匹配的社区。',
      noComponents: '未找到组件。请先打开左侧结构图加载社区列表。',
      startFailed: '启动失败: {msg}',
    },
    select: {
      modeActive: '已激活',
      modeExited: '已退出',
      modeStatus: '组件选择模式 {status}。在左侧结构图或标签视图中点选组件，选中后输入分析请求。',
      cleared: '已清除所有组件选择。',
      componentsSelected: '已选中 {count} 个组件。可输入 /analyze 启动批量分析...',
      etcMore: '等{count}个',
      count: '{count}个',
      typeCommunity: '社区',
      typeExternal: '外部包',
      removeRef: '移除引用',
      exitMode: '退出组件选择模式',
      selectComponent: '选择组件',
    },
    analyze: {
      forceOverwrite: '，强制覆盖',
      skipAnalyzed: '（跳过已分析）',
      submitted: '已提交 {count} 个组件的 Agent 多轮分析任务{hint}：{names}。请到「任务」面板查看进度。',
    },
    presummary: {
      started: '预摘要 P0→P1→P2 已启动{hint}。请到「任务」面板查看进度。',
    },
    overview: {
      started: '架构概览生成任务已启动，请稍后查看结果...',
      pendingAnalysis: '组件分析尚未完成，无法生成架构概览。请先执行 /analyze 或 /pipeline 完成组件分析后再试。',
    },
    retry: {
      forceOverwriteAll: '（强制覆盖所有）',
      skipSuccessful: '（跳过成功步骤）',
      started: '重新执行已启动{hint}。请到「任务」面板查看进度。',
    },
    messages: {
      showEarlier: '显示更早消息 ({count} 条)',
    },
    helpEntry: {
      hint: '输入 /help 或 /帮助 查看全部可用命令和模式',
    },
    langHint: {
      zh: '（中文）',
      en: '（English）',
    },
    common: {
      concurrency: '（并发 {n}）',
    },
  },
  ai: {
    assistantTitle: 'AI 助手',
    chatTab: '对话',
    assistantWelcome: '你好！我是 TopoCode AI 助手，可以帮你解答软件使用问题。输入 /help 查看可用命令。',
    assistantNotConfigured: 'LLM API 尚未配置，请在设置中完成配置。',
    goConfigure: '前往配置',
    inputPlaceholder: '输入问题... (Shift+Enter 换行)',
    typing: 'AI 正在输入...',
    clearChat: '清空对话',
  },

  // ====== 系统提示词：身份定义 ======
  systemPromptRole: `你是 TopoCode 桌面版使用助手，由 TopoCode 团队开发。
你仅回答与 TopoCode 软件功能和使用方法相关的问题。
对话使用中文回复。保持简洁。`,

  // ====== 系统提示词：能力范围规则 ======
  systemPromptScope: `## ✅ 可以回答
- TopoCode 软件功能说明（项目管理、分析任务、架构分析、代码解析等）
- 操作步骤指导（如何创建项目、配置任务、清理缓存等）
- 命令用法解释（/select, /analyze, /pipeline, /overview, /presummary, /retry, /help 等）
- 设置配置说明（LLM 模型添加/删除、后端 host/port/memory 配置、语言切换等）
- 界面导航指引（各面板、页面切换、按钮功能等）
- 常见问题排查（任务失败原因、缓存清理、导入导出问题等）

## ❌ 禁止回答
- 用户所分析项目的代码架构、设计模式、实现细节（请引导使用 Web AI 助手：http://localhost:3456/chat）
- 通用编程问题、算法实现、技术选型建议
- 非 TopoCode 的第三方工具使用方法
- 政治、个人观点、敏感话题

对于超出范围的问题，请直接回复："抱歉，这超出了我的回答范围。我是 TopoCode 使用助手，仅解答软件使用相关问题。"`,

  // ====== 内置知识：项目管理 ======
  docProject: `## 项目管理
### 创建项目
- 点击"新建项目"或拖拽目录到导入区域
- 选择要分析的源代码目录，系统会自动扫描文件结构

### 导入/导出
- 导入：点击工具栏"导入"按钮，选择之前导出的 .zip 存档文件
- 导出：点击工具栏"导出"按钮，勾选要导出的任务后下载 .zip 文件

### 项目操作
- 同步：刷新项目的文件树结构，检测文件变更
- 删除：移除项目及其分析数据（可在设置中确认）
- 编辑：修改项目名称、路径
- 分组：将项目分配到不同分组便于管理
- 收藏/置顶：标记常用项目便于快速访问`,

  // ====== 内置知识：分析任务 ======
  docAnalysisTask: `## 分析任务
### 新建任务
- 点击工具栏"新建任务"打开配置表单
- 选择语言类型：Python、JavaScript/TypeScript、Java、Go、C/C++、Rust 等
- 选择扫描目录范围（可选子目录）
- 选择报告类型：
  - 依赖分析（dependency）：分析文件/模块间的依赖关系
  - 调用链分析（call chain）：分析函数调用关系链
  - 支持同时选择多种类型
- 点击确定后任务进入队列自动执行

### 任务操作
- 运行/停止：控制任务执行状态
- 重新执行：对已完成或失败的任务重新运行
- 查看结果：点击任务行的"结构分析"跳转至架构分析页面
- 查看日志：查看任务运行过程中的详细日志
- 编辑配置：修改任务的参数设置
- 收藏/置顶：标记重要任务

### 任务状态说明
- pending：队列中等待执行
- running：正在执行
- completed：执行完成
- failed：执行失败
- cancelled：已取消`,

  // ====== 内置知识：架构分析 ======
  docArchAnalysis: `## 架构分析
架构分析页面展示项目的模块结构分析结果。

### 社区图（Community Graph）
- 以力导向图（Force-Directed Graph）展示模块间关系
- 每个节点代表一个社区（功能模块），边代表依赖/调用关系
- 支持缩放、拖拽、点击查看详情

### 命令操作（在 AI 助手输入框中输入）
- /select：组件选择模式。无参数时手动点选；支持 --all（全选）、--include/--call（按边类型）、--l0~--l5（按层级）、--clear（清除）、--unanalyzed（只选未分析）
- /analyze [-j N] [--force] [-L zh/en]：批量分析组件。--force 强制覆盖，-j 并发数 1-5，-L 语言
- /presummary [-j N] [--force]：文件预摘要 P0→P1→P2
- /overview [--force] [-L zh/en]：生成整体架构概览
- /pipeline [-j N] [--force] [-L zh/en]：一键流水线，顺序执行：项目摘要→预摘要→组件分析→架构概览
- /retry [--force]：重新执行流水线`,

  // ====== 内置知识：代码解析 ======
  docCodeAnalysis: `## 代码解析
### 浏览文件
- 左侧文件树展示项目的目录和文件结构，目录逐层展开（懒加载）
- 点击文件名在右侧查看源码，支持语法高亮
- 文件树顶部搜索框可按文件名快速筛选

### 管理任务
- 任务列表中可查看各任务的状态、进度和结果
- 支持对已完成/失败的任务重新执行，对运行中的任务停止
- 点击任务行的"结构分析"跳转至架构分析页面查看详细报告`,

  // ====== 内置知识：缓存管理 ======
  docCache: `## 缓存管理
### 清理缓存
在工具栏 ⚙️ 菜单 → "清理缓存" 中，可按类别选择性清除：
- 调用链分析缓存
- AI 问答缓存
- 符号索引缓存
- 社区分析缓存
- 文件摘要缓存
- 概览文档缓存

清除后相关数据会重新生成。`,

  // ====== 内置知识：设置 ======
  docSettings: `## 设置
### LLM 模型配置
- 支持添加多种模型服务商：Ollama（本地）、OpenAI 兼容 API、vLLM 等
- 填写 API 地址、模型名称、API Key 等信息
- 可设置默认模型，测试连接是否可用

### 后端配置
- HTTP Host：后端服务监听地址（默认 127.0.0.1）
- HTTP Port：后端服务端口（默认 3456）
- 内存限制：Python 后端进程的最大内存使用量（单位 MB）

### 其他设置
- 语言切换：支持简体中文、English
- 字体大小：调整编辑器字体
- 自动保存间隔：设置自动保存时间（秒）`,

  // ====== 内置知识：分组管理 ======
  docGroups: `## 分组管理
- 创建分组：命名并选择父分组（支持树形层级结构）
- 编辑分组：修改分组名称
- 删除分组：移除分组（不会删除其中的项目）
- 将项目分配到分组，便于按类别管理多个项目
- 在项目列表顶部可按分组筛选项目`,

  // ====== 内置知识：常见问题 ======
  docTroubleshooting: `## 常见问题排查
### 任务执行失败
- 检查源代码目录是否包含可分析的文件
- 确认语言类型选择是否正确
- 查看任务日志获取详细错误信息
- 尝试重新执行任务

### 后端无法启动
- 检查端口（默认 3456）是否被占用
- 检查 Python 环境是否正确安装
- 在设置中调整内存限制

### LLM 连接失败
- 确认模型服务是否在运行
- 检查 API 地址和端口是否正确
- 点击"测试连接"验证配置

### 分析结果不更新
- 点击"同步"刷新文件变更
- 重新执行分析任务
- 如有必要可清理缓存后重新分析`,

  helpHint: '输入 /help 或 /帮助 查看全部可用命令和模式',

  // ====== ChatView（报告页架构分析 Agent） ======
  chatSystemPrompt: `你是 TopoCode 架构分析助手，由 TopoCode 团队开发。
你专注于帮助用户分析项目架构、理解代码结构、发现依赖关系和调用链。

## 能力范围
- 分析项目模块划分和架构层次
- 解释组件之间的依赖和调用关系
- 生成架构概览和文档
- 检查代码架构质量问题（循环依赖、Hub 过载等）

## 禁止范围
- TopoCode 软件使用问题（请使用右侧栏 AI 助手）
- 通用编程问题、算法实现

回答应简洁、专业，使用图表辅助说明（Mermaid/PlantUML）。`,

  chatWelcome: '你好！我是 TopoCode 架构分析 Agent。我可以帮你分析项目架构、生成文档、检查代码质量。',

  // ====== 命令参考 ======
  helpCommands: `## 可用命令
| 指令 | 说明 |
|------|------|
| /help / /帮助 | 显示本帮助 |
| /select [--all/--include/--call/--l0~/--l5/--clear/--unanalyzed] | 组件选择模式。无参数时切换选择模式；--all 全选；--include/--call 按边类型筛选；--l0~--l5 按层级筛选；--clear 清除；--unanalyzed 只选未分析 |
| /presummary [-j N] [--force] | 文件预摘要 P0→P1→P2。--force 强制覆盖，-j N 并发数 1-5 |
| /analyze [-j N] [--force] [-L zh/en] | 批量组件分析。--force 强制覆盖，-j 并发，-L 语言 |
| /overview [--force] [-L zh/en] | 生成整体架构概览 |
| /pipeline [-j N] [--force] [-L zh/en] | 一键流水线：项目摘要→预摘要→组件分析→架构概览 |
| /retry [--force] | 重新执行流水线 |

## 交互模式
- **自由对话**：输入 TopoCode 使用相关问题
- **组件选择模式**：/select 切换，选中后 /analyze 分析
- **流水线模式**：/pipeline 一键全流程`,

  // ====== 代码解析帮助（用于代码解析页面） ======
  helpCode: `## 代码解析使用指南

### 1. 浏览项目文件
- 左侧**文件树**展示项目的目录和文件结构，目录逐层展开（懒加载）
- 点击文件名在右侧查看源码，支持语法高亮
- 文件树顶部搜索框可按文件名快速筛选

### 2. 创建分析任务
- 点击工具栏 **"新建任务"** 打开任务配置表单
- 选择要扫描的**语言类型**（Python、JavaScript 等）和**目录范围**
- 选择**报告类型**：依赖分析（dependency）、调用链分析（call chain）
- 点击确定后任务自动进入队列执行，可在任务列表查看进度

### 3. 管理任务
- 任务列表中可查看各任务的状态、进度和结果
- 支持对已完成/失败的任务**重新执行**，对运行中的任务**停止**
- 点击任务行的 **"结构分析"** 跳转至架构分析页面查看详细报告

### 4. 数据管理
- **导入分析结果**：工具栏"导入"按钮，选择之前导出的 .zip 存档
- **导出分析结果**：工具栏"导出"按钮，勾选要导出的任务后下载
- **校验文件**：工具栏"校验"按钮，检查文件 hash 是否与分析数据一致
- **清理缓存**：工具栏 ⚙️ 菜单 → 清理缓存，按类别选择性清除`,
}
