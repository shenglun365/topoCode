/**
 * FakeLLM — OpenAI 兼容假 LLM（fetch 注入）。
 *
 * 拦截 {baseUrl}/chat/completions（SSE 流式响应）与 {baseUrl}/models，
 * 按脚本逐回合出牌；记录全部请求体供上下文保持断言。
 *
 * 脚本条目：
 *   {type:"text", text}                    纯文本回复（回合自然完成）
 *   {type:"tool_call", name, args}         发起一次工具调用（finish=tool_calls）
 *   {type:"hang", resolve}                 挂起（abort 测试）；resolve() 手工放行
 *   {type:"error", status, body}           返回 HTTP 错误
 */

export interface FakeRequest {
  url: string;
  body: Record<string, unknown>;
}

export type FakeScriptEntry =
  | { type: "text"; text: string }
  | { type: "tool_call"; name: string; args: Record<string, unknown> }
  | { type: "hang"; resolve: () => void }
  | { type: "error"; status: number; body: string };

function sse(delta: Record<string, unknown>, finish: string | null = null): string {
  return `data: ${JSON.stringify({
    id: "chatcmpl-fake",
    object: "chat.completion.chunk",
    created: 1,
    model: "fake-model",
    choices: [{ index: 0, delta, finish_reason: finish }],
  })}\n\n`;
}

export class FakeLLM {
  requests: FakeRequest[] = [];
  script: FakeScriptEntry[] = [];

  private _hangResolvers: Array<() => void> = [];

  /** 放行所有挂起中的请求（abort 测试用）。 */
  releaseHangs(): void {
    for (const r of this._hangResolvers.splice(0)) r();
  }

  /** 某回合请求的 messages（请求序号从 0 起）。 */
  messagesOf(idx: number): Array<Record<string, unknown>> {
    const messages = this.requests[idx]?.body?.messages;
    return Array.isArray(messages) ? messages as Array<Record<string, unknown>> : [];
  }

  reset(): void {
    this.requests = [];
    this.script = [];
    this._hangResolvers = [];
  }

  fetch(): typeof fetch {
    return async (input: unknown, init?: unknown) => {
      const url = String(typeof input === "string" ? input : (input as { url?: string })?.url || input);
      const bodyRaw = (init as { body?: string })?.body;
      let body: Record<string, unknown> = {};
      try {
        body = bodyRaw ? JSON.parse(bodyRaw) : {};
      } catch {
        body = {};
      }
      if (url.includes("/models")) {
        return new Response(JSON.stringify({ data: [{ id: "fake-model" }] }), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }
      if (!url.includes("/chat/completions")) {
        return new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }
      this.requests.push({ url, body });
      const entry = this.script.shift();
      if (!entry || entry.type === "text") {
        const text = entry && entry.type === "text" ? entry.text : "";
        const payload =
          sse({ role: "assistant", content: "" })
          + sse({ content: text })
          + sse({}, "stop")
          + "data: [DONE]\n\n";
        return new Response(payload, {
          status: 200,
          headers: { "content-type": "text/event-stream" },
        });
      }
      if (entry.type === "tool_call") {
        const payload =
          sse({ role: "assistant", content: "" })
          + sse({
              tool_calls: [{
                index: 0,
                id: `call_${this.requests.length}`,
                type: "function",
                function: { name: entry.name, arguments: JSON.stringify(entry.args) },
              }],
            })
          + sse({}, "tool_calls")
          + "data: [DONE]\n\n";
        return new Response(payload, {
          status: 200,
          headers: { "content-type": "text/event-stream" },
        });
      }
      if (entry.type === "error") {
        return new Response(entry.body, { status: entry.status });
      }
      // hang
      const p = new Promise<Response>((resolve) => {
        this._hangResolvers.push(() => {
          resolve(new Response(
            sse({ role: "assistant", content: "" })
            + sse({ content: "released" })
            + sse({}, "stop")
            + "data: [DONE]\n\n",
            { status: 200, headers: { "content-type": "text/event-stream" } }));
        });
      });
      return p;
    };
  }
}
