# UI/UE 设计方案 — Agent 驱动工作流

> 版本: v1.0 | 日期: 2026-06-09 | 状态: 待实现
> 
> 基于 `agent相关功能改版文档.md` v5.2 的目标和框架方案

---

## 一、核心理念

从"工具操作界面"升级为"认知对话界面"。用户不再操作 pipeline 步骤，而是与 Agent 对话来探索架构。

```
旧模式:  用户选模板 → 点按钮 → 看进度条 → 等结果 → 打开文档
新模式:  用户问问题 → Agent 思考 → 展示洞察 → 用户追问 → 迭代深入
```

## 二、页面布局

```
┌──────────────────────────────────────────────────────────────┐
│  topocode                                               [≡]  │
├───────────────────────────────────────────┬──────────────────┤
│                                           │                  │
│          ChatView (主对话区)               │   SessionPanel   │
│                                           │   (会话历史)      │
│  ┌─────────────────────────────────────┐  │                  │
│  │  Agent: 这个项目是 3 层架构...       │  │  ┌────────────┐  │
│  │  [Mermaid 依赖图]                    │  │  │ 会话 1      │  │
│  │  [关键社区列表]                      │  │  │ 会话 2      │  │
│  └─────────────────────────────────────┘  │  │ 会话 3      │  │
│                                           │  └────────────┘  │
│  ┌─────────────────────────────────────┐  │                  │
│  │  用户: auth 模块的认证流程怎么实现？  │  │  Architecture    │
│  └─────────────────────────────────────┘  │  Explorer        │
│                                           │  (架构树浏览)     │
│  ┌─────────────────────────────────────┐  │                  │
│  │  Agent: authenticate 是...           │  │  ┌─ 表示层      │  │
│  │  [调用流程图]                        │  │  │  ├─ auth    │  │
│  └─────────────────────────────────────┘  │  │  ├─ api     │  │
│                                           │  │  ├─ ...     │  │
│  ┌──────────────────────────────┐         │  └────────────┘  │
│  │ 输入框                        │  [→]    │                  │
│  └──────────────────────────────┘         │                  │
├───────────────────────────────────────────┴──────────────────┤
│  [/] 模型: deepseek-v4-flash  |  📄 查看架构文档              │
└──────────────────────────────────────────────────────────────┘
```

## 三、核心组件

### 3.1 ChatView（主对话区）

- **继承**: 扩展 `AIAssistantPanel.vue` 的对话能力
- **新增**:
  - Agent 思考过程展示（tool calls 透明化）
  - Markdown 渲染（marked.js）
  - Mermaid 实时渲染（mermaid.js）
  - PlantUML 图片加载
  - 一键追问按钮（"深入这个模块"、"生成架构文档"）
  - 架构洞察卡片（不是原始数据，是提炼后的认知）
- **状态**: 新建 `src/components/report/ChatView.vue`

### 3.2 ArchitectureExplorer（架构树）

- **功能**: 社区树形浏览 + drill-down
  - L0 社区列表 → 点击展开子社区 → 点击展开文件 → 点击展开符号
  - 每个节点显示简要摘要（不是数据列表）
  - Hub 节点高亮
- **替代**: 旧的 `CommunitySection.vue` + `ChildAnalysisPanel.vue`
- **状态**: 新建 `src/components/report/ArchitectureExplorer.vue`

### 3.3 ReportViewer（文档/图查看器）

- **功能**: 独立的 Markdown 文档 + 图渲染界面
  - 全屏查看生成的架构文档
  - Tab 切换：总览 / 依赖图 / 调用图 / 社区详情
  - 图再生功能（skill_fix_diagram 触发）
- **替代**: 旧的 `SubDocViewer.vue`（保留其渲染能力）
- **状态**: 扩展 `src/components/report/SubDocViewer.vue`

### 3.4 SessionPanel（会话历史）

- **功能**:
  - 列出历史 AI 会话（从 ai_sessions 表读取）
  - 点击可查看该会话的变更摘要
  - 显示质量评分
- **状态**: 新建 `src/components/report/SessionPanel.vue`

## 四、用户交互流程

### 4.1 项目分析完成 → 查看结果

```
1. 用户在项目页点击"开始分析"
2. Agent 自动运行 5 步分析管线（后端已有）
3. 分析完成后，Agent 自动发送第一条消息：
   "分析完成。项目包含 42 个社区，3 层架构。
   核心子系统是 auth（12 节点，Hub=authenticate）。
   你想先了解哪个部分？"
4. 快捷按钮: [查看架构总览] [深入 auth 模块] [质量检查]
```

### 4.2 探索架构

```
用户: "auth 模块怎么设计的？"
Agent:
  ① 调用 topocode_community_detail("auth-community")
  ② 调用 skill_explain_arch_pattern("auth-community")
  ③ 输出:
     "auth 是业务层的中心子系统。它的核心是 authenticate（Hub 节点，度=15）。
      它连接了表示层（接收请求）和安全层（JWT 验证），是系统的安全边界。
      
      选择 JWT 而非 session 是因为无状态扩展需求，但引入了 token 撤销难的问题。
      这个权衡值得关注。"
  ④ 附带 Mermaid 调用图
```

### 4.3 生成文档

```
用户: "生成完整架构文档"
Agent:
  ① 调用 skill_batch_analyze_communities
  ② 调用 skill_generate_arch_overview
  ③ 输出:
     [Markdown 文档预览]
     [Mermaid 依赖图]
     [Mermaid 调用图]
  ④ 快捷按钮: [保存文档] [导出 PDF] [继续完善]
```

### 4.4 质量检查

```
用户: "代码质量怎么样？"
Agent:
  ① 调用 topocode_quality_inspect
  ② 输出:
     "发现 3 个 HIGH 级别问题：
      - auth/handler.ts:42 — authenticate 缺少测试覆盖
      - middleware/auth.ts:15 — 疑似硬编码密钥
      - api/ — api 社区 Hub 节点过载（degree=22，建议拆分）
     需要我详细分析哪个问题？"
```

## 五、组件树

```
src/components/report/
├── ChatView.vue              ← 新建: 主 Agent 对话界面
├── ArchitectureExplorer.vue  ← 新建: 社区树 + drill-down
├── SessionPanel.vue          ← 新建: 会话历史列表
├── SubDocViewer.vue          ← 重用: 文档/图渲染
├── SubDocContent.vue         ← 重用: Markdown 内容渲染
├── SubDocToolbar.vue         ← 重用: 图操作工具栏
├── SubDocRegenDialog.vue     ← 重用: 图再生对话框
├── SymbolDetailCard.vue      ← 重用: 符号详情卡片
├── EdgeDetailCard.vue        ← 重用: 边详情卡片
├── CommunityNodeCard.vue     ← 重用: 社区节点卡片
├── CommunitySection.vue      ← 保留: 社区列表展示（集成到 Explorer）
├── ChildSection.vue          ← 保留: 子社区展示
├── ChildAnalysisPanel.vue    ← 保留: 子社区分析面板
├── ReportHome.vue            ← 重写: 简化为入口 + Agent 对话
├── ReportTaskListPanel.vue   ← 保留: 任务列表（简化）
├── PipelineTaskTree.vue      ← 保留: 任务状态树（简化）
├── CodeIndexPanel.vue        ← 保留: 代码索引
└── ReportHome.vue            ← 更新: 移除 pipeline，添加 ChatView

src/pages/
└── AnalysisPage.vue          ← 更新: 使用新组件布局
```

## 六、实施计划

| 步骤 | 内容 | 预估 |
|------|------|------|
| 1. 创建 `ChatView.vue` | Agent 对话界面 + Markdown/Mermaid 渲染 | 0.5天 |
| 2. 创建 `ArchitectureExplorer.vue` | 社区 drill-down 树 | 0.3天 |
| 3. 创建 `SessionPanel.vue` | 会话历史列表 | 0.2天 |
| 4. 更新 `AnalysisPage.vue` | 新布局集成所有组件 | 0.3天 |
| 5. 更新 `ReportHome.vue` | 移除 pipeline，接入 ChatView | 0.3天 |
| 6. 构建验证 + 调试 | 确保编译通过、交互正常 | 0.2天 |
