# 错误契约（error-contract）

> cv-175 规范化·环节三。原则：**错误形状按层固定，跨层不混用；错误必须明确，禁止静默降级**。

## 分层规则

| 层 | 成功形状 | 失败形状 | 说明 |
|---|---|---|---|
| **工具层**（`run_arch_tool` 及注册 handler） | 结果 dict（无 `error` 键） | `{"error": "原因"}` | `run_arch_tool` 统一判定：dict 含 `error` 键即失败 |
| **感知/编排直通**（`perception/commands.py`） | `{"ok": True, "receipt"?: str, "task"?: dict}` | `{"ok": False, "receipt"?: str}` / `{"ok": False, "noPending": True}` | 直通命令的回执统一走 `receipt` 文本，编排层原样落流 |
| **编排执行器**（`exec_bridge.propose_task/confirm_task`） | 任务 dict **含 `"ok": True`** | `{"ok": False, "error": "原因"}` | 成功形状显式 ok（历史 task dict 兼容：调用方 `get("id")` 判定仍有效） |
| **异常通道**（可恢复配置类错误） | — | `raise ModelNotConfigured(...)` 等明确异常 | 不允许被宽泛 except 吞成 None；REST 边界映射 4xx |
| **REST 边界** | `ok(data)` → `{"code": 0, message, data}` | `err(code, msg)` → HTTP **status=code**，body `{"code", "message", "data": None}` | 前端 api-client 只解析 `body.code`，HTTP 状态码与 body.code 一致 |

## 状态码语义（REST）

- `400` 参数/请求非法 · `403` 越权 · `404` 不存在
- `409` 冲突（互斥/重复） · `424` 依赖失败（上游任务/规约未满足）
- `500` 内部错误 · `502` 上游不可达（runner/llm） · `503` 服务未就绪

## 纪律

1. **禁止** `except: pass` 吞错误后返回成功形状（审计: SSE/cards 落流类辅助可吞，业务结果不可）。
2. **禁止** 把用户可修复的错误（配置缺失、参数非法）包成 500。
3. 错误文案必须**可直接行动**（告诉用户下一步：改什么配置/发什么指令）。
4. 兜底/降级一律禁止（cv-168 裁决）——唯一例外：SSE 通知类尽力而为。
