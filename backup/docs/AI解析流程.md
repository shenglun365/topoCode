# AI 分析调用流程

## `community_analyze`（流水线批量社区分析）

```
7. onDone → task.name / task.summary / task.status = 'completed'
8. → saveCommunityResult()                                                  task_manager.py:450
                                                                               → analysis_store.list_llm_results SELECT / INSERT
                                                                               → community_llm_results 表写入
9. → emit('completed')                                                       
      → ReportGenerationPipeline.vue:432
        → emit('communityResults')
          → ReportHome.vue:148
            reloadCommunityResults()
              → listCommunityResults() 重新拉取
              → 更新 commResults / chip-name

## PlantUML 渲染流程（AI 输出）

```
LLM 生成 PlantUML
  ↓
SubDocViewer.vue / LLMChatFlow.vue
  → 检测 ```plantuml 代码块
  → 提取代码，发送到后端 render.plantuml API
  ↓
backend/plantuml_service.py:render_plantuml()
  │
   ├─ _sanitize_plantuml(code)  # 清洗 LLM 非标准语法
   │   ├─ box ... end → package {} component (plantuml.com 不支持 box)
   │   ├─ A [src] -uses> B [dst] → [src] --> [dst] : uses
   │   ├─ file router.js → "router.js"
   │   └─ 添加缺失 @startuml/@enduml 包装
  │
   ├─ encode_plantuml(code)      # PlantUML 自定义 base64 编码
   │   └─ 字母表: 0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_
   │   └─ deflate → 6bit 分组 → 自定义字母映射 (非标准 base64)

   └─ 渲染
       ├─ 远程: plantuml.com/{format}/{encoded}
       └─ 本地: java -jar plantuml.jar -tpipe
  ↓
返回 base64 编码的图片数据
  ↓
前端渲染为 <img src="data:image/svg+xml;base64,...">
```

### 支持的 LLM PlantUML 格式

**非标准 (LLM 输出)** → **标准 (PlantUML 接受)**
1. `A [file.c] -uses> B [header.h]` → `[file.c] --> [header.h] : uses`
2. `file router.js --> file handler.js` → `"router.js" --> "handler.js"`
3. `router.js --> handler.js` → `"router.js" --> "handler.js"`
4. 裸文件名自动加引号: `main.c` → `"main.c"`

**要求**:
- PlantUML 版本固定: `plantuml==1.2024.7`
- 错误处理: `SubDocViewer.vue` 显示错误信息和原始代码，便于调试
- 调试模式: 前端可查看原始代码和清洗后代码对比

## 相关文件

| 文件 | 角色 |
|---|---|
| `backend/prompt_manager.py` | 内置模板定义（`community_analyze`） |
| `backend/llm_service.py` | `llm.chat` 入口，模板渲染 + LLM 流式调用 |
| `backend/task_manager.py` | `saveCommunityResult` (L450), `getCascadeLevels` (L1155) |
| `backend/core_service.py` | `getLevelCommunityDetail` (L1679) |
| `backend/community_analysis.py` | Louvain 社区检测，写入 `graph_doc` 表 |
| **`backend/plantuml_service.py`** | **PlantUML 渲染服务：清洗 LLM 非标准语法，自定义 base64 编码，自动包装** |
| `backend/store/analysis_store.py` | `graph_doc` / `community_llm_results` CRUD |
| `src/components/report/CommunityAnalysisPipeline.vue` | 流水线批量分析 UI + `runTask()` |
| `src/components/report/ReportHome.vue` | 社区概要显示 + `reloadCommunityResults()` |
| `src/components/report/ReportGenerationPipeline.vue` | 事件转发 `completed` → `communityResults` |
| `src/pages/AnalysisPage.vue` | 页面协调：open-md |
| **`src/components/report/SubDocViewer.vue`** | **子文档查看器：渲染 PlantUML 代码块，显示错误信息，支持调试** |
| **`src/components/report/LLMChatFlow.vue`** | **LLM 对话界面：输出 PlantUML 代码块，自动渲染** |
