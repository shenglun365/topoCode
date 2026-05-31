# LLM 调用流程评估报告

## 一、完整调用链路图

```
┌─────────────────────────────────────────────────────────────────────┐
│  Vue 组件层                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────┐  ┌───────────┐ │
│  │AIAssistant   │  │ReportAIPanel │  │CommunityAna │  │SymbolDetail│ │
│  │Panel.vue     │  │.vue          │  │lysisPipeline│  │Card.vue   │ │
│  └──────┬───────┘  └──────┬───────┘  │.vue         │  └─────┬─────┘ │
│         │                 │           └──────┬───────┘        │       │
│  ┌──────┴───────┐  ┌──────┴───────┐  ┌──────┴───────┐  ┌─────┴─────┐ │
│  │LLMChatFlow   │  │CommunityNode │  │EdgeDetailCard│  │ReportGen  │ │
│  │.vue          │  │Card.vue      │  │.vue          │  │Pipeline   │ │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  │.vue       │ │
│         │                 │                 │           └─────┬─────┘ │
├─────────┼─────────────────┼─────────────────┼─────────────────┼───────┤
│  Service层               │                 │                 │       │
│         │                 │                 │                 │       │
│  ┌──────┴────────┐  ┌────┴────────┐  ┌─────┴───────┐  ┌──────┴──────┐│
│  │ llmClient.ts  │  │chat store   │  │useLlmChat   │  │ ipc.ts     ││
│  │ (chat/explain │  │(sendMessage)│  │composable   │  │ (wrapper)  ││
│  │ Symbol/Edge/  │  └──────┬──────┘  └──────┬───────┘  └─────────────┘│
│  │ Community/    │         │                 │                        │
│  │ summarize)    │         │                 │                        │
│  └──────┬────────┘         │                 │                        │
├─────────┼──────────────────┼─────────────────┼────────────────────────┤
│  preload.ts (IPC Bridge)   │                 │                        │
│         │                  │                 │                        │
│  ┌──────┴──────────────────┴─────────────────┴──────────────┐        │
│  │  window.api.llm: {chat, explainSymbol, summarizeCode,    │        │
│  │                    subscribe, abortChat}                  │        │
│  │  window.api.promptTemplate: {list, get, create, ...}     │        │
│  └──────────────────────────┬───────────────────────────────┘        │
├─────────────────────────────┼────────────────────────────────────────┤
│  backend (ZMQ IPC)          │                                        │
│                             │                                        │
│  ┌─────────────────────────┴──────────────────────────────────────┐ │
│  │  register_llm_methods()  (llm_service.py)                      │ │
│  │                                                                │ │
│  │  ┌───────────────────┐   ┌──────────────────┐                  │ │
│  │  │ llm.chat (v2)     │   │llm.explainSymbol │                  │ │
│  │  │ → streaming_chat  │   │ → _explain_symbol│  ← 废弃路径①    │ │
│  │  │   → _execute_     │   │   (sync, non-    │                  │ │
│  │  │     streaming()   │   │    streaming)     │                  │ │
│  │  │   → thread stream │   └──────────────────┘                  │ │
│  │  │   → ZMQ PUB       │   ┌──────────────────┐                  │ │
│  │  │                   │   │llm.summarizeCode  │  ← 死代码②     │ │
│  │  │   PromptManager   │   │ → _summarize_code │                  │ │
│  │  │   .render()       │   └──────────────────┘                  │ │
│  │  └───────────────────┘                                        │ │
│  └────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 二、冗余问题 (Redundancy)

### R1. 同一提示词在三个地方重复定义

| 提示词 | `prompt_manager.py` (模板) | `backend/llm_service.py` (内联) | `src/services/llmClient.ts` (内联) |
|--------|:---:|:---:|:---:|
| summarizeCode / src_to_pseudocode | ✅ `src_to_pseudocode` | ✅ `_summarize_code()` L133-137 | ✅ `summarizeCode()` L196-197 |
| explainSymbol / source_explain | ✅ `source_explain` | ✅ `_explain_symbol()` L169-173 | ✅ `explainSymbol()` L102-126 |
| explainCommunity / community_explain | ✅ `community_explain` | ❌ | ✅ `explainCommunity()` L170-178 |
| summarizeCommunityName / community_name | ✅ `community_name` | ❌ | ✅ `summarizeCommunityName()` L219-224 |

**影响**: 修改提示词需要同步修改3处，极易产生不一致。例如 `src_to_pseudocode` 模板支持 `{language}` 变量，但 `llmClient.ts:summarizeCode()` 硬编码了不带语言标记的 prompt。

### R2. 两条并行的 LLM 调用路径

| 路径 | llmClient 方法 | 后端路由 | 是否流式 |
|------|---------------|---------|:-------:|
| A: 通用 chat 路径 | `chat()`, `explainEdge()`, `explainCommunity()`, `summarizeCode()`, `summarizeCommunityName()` | `llm.chat` → `streaming_chat()` | ✅ |
| B: 专用 RPC 路径 | `explainSymbol()` | `llm.explainSymbol` → `_explain_symbol()` | ❌ |

`explainSymbol` 走的是 **非流式同步路径**（`_call_llm` → `asyncio.to_thread(_sync_call_ollama_chat)`），而其他4个业务方法走的是 **流式路径**（`streaming_chat` → `_sync_stream_ollama`）。两条路径使用完全不同的 HTTP 请求逻辑。

### R3. `PromptManager` 在 RPC 注册处反复创建

```python
# llm_service.py:1182, 1306, 1313, 1330, 1341, 1348, 1354
@server.register('llm.chat')
def chat(...):
    from prompt_manager import PromptManager
    pm = PromptManager(multi_db)  # ← 每次调用都创建新实例
```

每个 RPC handler 都独立 `import` + 实例化 `PromptManager`，没有在 `register_llm_methods` 中统一初始化并复用。

### R4. 前端有2个独立的流式订阅入口

| 组件/模块 | 订阅方式 |
|-----------|---------|
| `chat store` (chat.ts:253) | `api().llm.subscribe(result.requestId, {...})` |
| `useLlmChat` composable (useLlmChat.ts:135) | `window.api.llm.subscribe(result.requestId, {...})` |
| `LLMChatFlow.vue` (L179) | 直接 `window.api.llm.subscribe(...)` |
| `CommunityAnalysisPipeline.vue` (L384) | 直接 `window.api.llm.subscribe(...)` |
| `ReportGenerationPipeline.vue` (L245) | 直接 `window.api.llm.subscribe(...)` |
| `ReportAIPanel.vue` (L154) | 直接 `window.api.llm.subscribe(...)` |
| `llmClient.ts:chat()` (L64) | 内部 `bridge.llm.subscribe(...)` |

**问题**: 流式订阅的逻辑（subscribe → 事件分发 → unsubscribe）在 7 个地方重复实现。尤其是每个组件都要手动处理 `onChunk` 拼接 content。

### R5. 手动维护 camelCase / snake_case 兼容

```python
# llm_service.py 几乎所有 RPC handler
session_id = session_id or sessionId
model_id = model_id or modelId
template_id = template_id or templateId
```

30+ 处重复，且没有统一拦截器/中间件处理。

---

## 三、失效/死代码 (Dead Code)

### D1. `llm.summarizeCode` RPC — 完全不被前端调用

- 后端注册: `llm_service.py:1359` `@server.register('llm.summarizeCode')`
- 前端 preload 暴露: `preload.ts:325`
- 但 `llmClient.ts:summarizeCode()` 调用的是 `window.api.llm.chat({messages: ...})` 而非 `window.api.llm.summarizeCode()`
- **无任何前端代码调用 `window.api.llm.summarizeCode()`**

### D2. `prompt_manager.py:preview()`— 无意义包装

```python
def preview(self, template_id, variables):
    """预览渲染结果（不调用 LLM）"""
    return self.render(template_id, variables)  # 直接委托给 render
```

`render_template` RPC (`llm_service.py:1351`) 调用 `pm.preview()` 但没有做任何额外处理，可以直接调用 `render()`。

### D3. `session.saveMessages` RPC — 未被前端消费

- 后端注册: `llm_service.py:1216`
- preload 暴露: `preload.ts:306`
- 但 `chat store` 和 `useLlmChat` 直接调用 `session.addMessage` 单条保存
- **无前端代码调用 `session.saveMessages`**

### D4. `backend/llm_service.py` 中的同步调用函数

```python
_call_llm()          # L93 — 仅被 _summarize_code / _explain_symbol 使用
_sync_call_ollama_chat()   # L39 — 仅被 _call_llm 使用
_sync_call_openai_chat()   # L64 — 仅被 _call_llm 使用
```

如果废弃 v1 的 `_summarize_code` / `_explain_symbol`（应迁移到模板系统），这 3 个函数连带成为死代码。

---

## 四、高耦合 (High Coupling)

### C1. `SymbolDetailCard.vue` 的 `onChunk` 回调被静默忽略

`SymbolDetailCard.vue:71`:
```typescript
const result = await explainSymbol(
  { symbolName: ..., symbolType: ..., codeSnippet: ..., fileName: ... },
  (chunk) => { aiContent.value += chunk }  // ← 这个参数被静默忽略!
)
```

`llmClient.ts:explainSymbol()` 的函数签名：
```typescript
export async function explainSymbol(
  params: { symbolName: string; symbolType: string; codeSnippet: string; fileName?: string }
): Promise<string>
```

**不接受第二个参数**，但 TypeScript 不报错（额外参数合法但被忽略）。回调永远不会执行，组件认为自己在实时更新但实际是空的。`EdgeDetailCard.vue` 有同样的问题（虽然 `explainEdge` 的第二个实参也被忽略，但 `explainEdge` 内部调用的是 `chat()` 流式路径，只是 `onChunk` 回调没有透传进去）。

### C2. `llm_service.py` 对 `PromptManager` 的紧耦合

- `chat()` RPC handler 内直接 import + 实例化 `PromptManager` (L1182-1183)
- 6 个 `promptTemplate.*` RPC handler 再次重复 import + 实例化
- `PromptManager.__init__` 每次都会调用 `_init_builtins()` 查库，有性能开销

### C3. 流式事件分发横跨 5 层

```
Python thread → ZMQ PUB → Electron main process → webContents.send()
→ preload.ts 'zmq:event' handler → component callback
```

任何修改（如添加新事件类型、修改数据结构）需要同步修改 5 个文件：
`llm_service.py` → `zmq_server.py` → `electron/main.ts` → `preload.ts` → 消费组件

### C4. 消息构建逻辑分散

构建 `messages` 数组的逻辑分散在：
- `backend/prompt_manager.py:render()` — 模板路径
- `backend/llm_service.py:_summarize_code() / _explain_symbol()` — v1 内联路径
- `src/services/llmClient.ts` — 5 个业务方法各有一套构建逻辑
- `src/stores/chat.ts:sendMessage()` — 过滤/切片/合并逻辑
- `src/components/report/LLMChatFlow.vue:sendFollowUp()` — 独立的过滤/合并/交替逻辑
- `src/components/report/ReportAIPanel.vue:sendMessage()` — 独立的过滤/切片逻辑

### C5. `LLMChatFlow.vue` 和 `chat store` 重复消息处理

两者都实现了：
- 过滤非 user/assistant 角色
- 确保首条为 user
- 合并连续同角色消息
- 确保以 user 结尾

但这些逻辑是 LLMChatFlow 自己实现的，没有复用 `chat store` 或 `useLlmChat`。

---

## 五、改进建议优先级

| 优先级 | 问题 | 建议方案 |
|--------|------|---------|
| P0 | `SymbolDetailCard.vue` 和 `EdgeDetailCard.vue` 的 `onChunk` 回调被忽略 | 修复 `explainSymbol` / `explainEdge` 签名，透传 `onChunk` 到内部 `chat()`；或改为使用 `templateId` |
| P0 | 同一提示词定义在3处重复 | 废弃 `llmClient.ts` 和 `llm_service.py` 中的内联 prompt，全部改为使用 `promptTemplate.render` |
| P1 | `llm.explainSymbol` 走非流式路径 | 将调用改为 `llm.chat` + `templateId` + 流式 |
| P1 | `llm.summarizeCode` 死代码 | 删除后端 `llm.summarizeCode` RPC 及 preload 声明 |
| P2 | `PromptManager` 在 RPC 中反复实例化 | 在 `register_llm_methods` 中统一创建一次实例 |
| P2 | 流式订阅逻辑重复 7 次 | 统一使用 `useLlmChat` composable，废弃其他直接 subscribe 路径 |
| P2 | 消息构建逻辑分散 6 处 | 将消息构建/过滤逻辑抽象为 `useChatMessages` composable |
| P3 | `prompt_manager.py:preview()` 冗余 | 直接删除，RPC 调用 `render()` |
| P3 | `session.saveMessages` 死代码 | 删除后端 RPC 及 preload 声明 |
| P3 | camelCase/snake_case 手动兼容 | 在 ZMQ IPC 层添加统一转换中间件 |
