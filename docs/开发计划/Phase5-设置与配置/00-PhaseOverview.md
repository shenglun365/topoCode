# Phase 5: 设置与配置 —— 集成总览

> 组件间协作流程、数据流、路由映射、Service 对接

---

## 1. Phase 目标

提供系统设置界面，管理 LLM 模型配置与路由、外部 CLI Agent、SKILL 校验扩展、通用偏好（主题/语言/端口）。

---

## 2. 组件清单与职责

| 编号 | 组件 | 设计文档 | 职责 |
|------|------|----------|------|
| 01 | **SettingsTabBar** | [01-SettingsTabBar.md](01-SettingsTabBar.md) | 设置页 Tab 导航 (模型/Agent/SKILL/通用/插件/关于) |
| 02 | **ModelConfig** | [02-ModelConfig.md](02-ModelConfig.md) | LLM 模型管理: 增删改/任务级绑定/用量限制/优先级 |
| 03 | **AgentManager** | [03-AgentManager.md](03-AgentManager.md) | 外部 CLI Agent 配置: 路径/参数/默认启用 |
| 04 | **SkillManager** | [04-SkillManager.md](04-SkillManager.md) | SKILL 校验拓展: 签名校验/依赖合规/安全/动画/风格 |
| 05 | **GeneralSettings** | [05-GeneralSettings.md](05-GeneralSettings.md) | 通用设置: 主题/语言/字体/HTTP服务 |
| 06 | **PluginManager** | [06-PluginManager.md](06-PluginManager.md) | 语言解析器插件管理: 安装/启用/禁用 |
| 07 | **AboutPage** | [07-AboutPage.md](07-AboutPage.md) | 版本信息/检查更新/查看日志 |

---

## 3. 组件协作流程

```
用户操作                    组件响应                         Service
──────────                ──────────                      ──────────
进入 /user 页面
    │
    ├── LeftPanel: SettingsTabBar
    │       └── 默认激活 "模型" Tab
    │
    └── MainContent: 根据 activeTab 渲染
            │
            ├── Tab: 模型 (ModelConfig)
            │       │
            │       ├── 加载: ModelService.list()
            │       │       └── ModelCard[] 列表 (name/type/status)
            │       │
            │       ├── 添加模型 → ModelConfig 弹出 ModelForm
            │       │       └── 填写 type/endpoint/model/apiKey
            │       │               └── ModelService.add()
            │       │
            │       ├── 测试连接 → ModelService.test(modelId)
            │       │       └── 返回 ping 结果 → 更新 StatusDot
            │       │
            │       ├── 设默认 → ModelService.setDefault(modelId)
            │       └── 删除 → ModelService.delete(modelId)
            │
            ├── Tab: Agent (AgentManager)
            │       │
            │       ├── 加载: AgentService.list()
            │       │       └── AgentCard[] 列表
            │       │
            │       ├── 添加 Agent → 填写 path/args
            │       │       └── AgentService.add()
            │       │
            │       ├── 测试 → AgentService.test(agentId)
            │       │       └── 检查 subprocess 可执行性
            │       │
            │       └── 设默认 → AgentService.setDefault(agentId)
            │
            ├── Tab: SKILL (SkillManager)
            │       │
            │       └── 内置 SKILL 列表 (单元测试生成/代码规范检查/安全扫描)
            │               ├── 开关 toggle → emit toggle
            │               └── 配置 config → emit config → 打开 SkillConfigForm
            │
            └── Tab: 通用 (GeneralSettings)
                    │
                    ├── 主题: dark / light / system
                    │       └── emit update({ theme }) → Pinia stores/theme.ts
                    │
                    ├── 语言: zh / en
                    │       └── emit update({ language }) → i18n 切换
                    │
                    ├── HTTP 端口: 默认 18080
                    │       └── emit update({ port }) → 写入配置
                    │
                    └── 自动启动: boolean
                            └── emit update({ autoStart }) → Electron auto-launch
```

---

## 4. 数据流

```
┌─────────────────────────────────────────────────────────────┐
│  Pinia stores                                              │
│                                                             │
│  stores/settings.ts                                         │
│    activeTab: 'model' | 'agent' | 'skill' | 'general'       │
│    models: ModelConfig[]            ← ModelService.list()   │
│    agents: AgentConfig[]            ← AgentService.list()   │
│    skills: SkillConfig[]            ← 内置 + 用户配置       │
│    general: GeneralSettings         ← 本地持久化            │
│                                                             │
│  stores/theme.ts  (Phase 1)                                 │
│    theme: 'dark' | 'light'          ← GeneralSettings 联动  │
└─────────────────────────────────────────────────────────────┘
```

---

## 5. Service 对接点

| 组件 | 调用 Service | API |
|------|-------------|-----|
| ModelConfig (列表) | ModelService | `GET /api/v1/models` |
| ModelConfig (操作) | ModelService | `POST/PUT/DELETE /api/v1/models` |
| ModelConfig (默认) | ModelService | `POST /api/v1/models/{id}/default` |
| ModelConfig (测试) | ModelService | `POST /api/v1/models/{id}/test` |
| AgentManager (列表) | AgentService | `GET /api/v1/agents` |
| AgentManager (操作) | AgentService | `POST/PUT/DELETE /api/v1/agents` |
| AgentManager (测试) | AgentService | `POST /api/v1/agents/{id}/test` |
| SkillManager | 无后端 API | (前端本地开关 + 配置) |
| GeneralSettings | 无后端 API | (Electron 本地存储，影响前端行为) |

---

## 6. 路由映射

```
/user                           → 设置主页 (默认 "模型" Tab)
/user/models                    → 模型配置
/user/agents                    → Agent 管理
/user/skills                    → SKILL 管理
/user/general                   → 通用设置
```

---

## 7. 依赖关系

```
Phase 1 (AppShell + LeftPanel + RightPanel)
    │
    └── Phase 5 组件挂载:
              ├── LeftPanel:   (可选：设置子导航，或由 Header 内的 Tab 替代)
              ├── MainContent: SettingsTabBar + 四个配置页
              └── RightPanel:  (通常隐藏)

Phase 4 (AI 助手)
    │
    └── Phase 5 配置的模型/Agent 直接影响 Phase 4 的对话和任务执行
```
