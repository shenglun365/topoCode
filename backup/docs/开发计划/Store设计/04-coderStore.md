# stores/coder.ts

> Phase 4: AI 助手状态管理

```typescript
import { defineStore } from 'pinia';

type SessionType = 'project' | 'general' | 'history';
type SessionStatus = 'active' | 'idle' | 'error';
type MessageRole = 'user' | 'assistant';
type MessageType = 'text' | 'context' | 'spec' | 'task' | 'error';
type ChatMode = 'chat' | 'design';

interface Session {
  id: string;
  name: string;
  type: SessionType;
  projectId?: string;
  status: SessionStatus;
  messageCount: number;
  group?: string;           // 分组 (如 "会话日志/知识库")
  createdAt: number;
}

interface ChatMessage {
  id: string;
  sessionId: string;
  role: MessageRole;
  type: MessageType;
  content: string;
  metadata?: Record<string, any>;
  timestamp: number;
}

export const useCoderStore = defineStore('coder', () => {
  // ---- State ----
  const sessions = ref<Session[]>([]);
  const activeSessionId = ref<string | null>(null);
  const messages = ref<ChatMessage[]>([]);
  const loading = ref(false);
  const streamingContent = ref('');
  const chatMode = ref<ChatMode>('chat');

  // ---- Getters ----
  const activeSession = computed(() =>
    sessions.value.find(s => s.id === activeSessionId.value) ?? null
  );

  const sessionGroups = computed(() => {
    const groups = new Map<string, Session[]>();
    sessions.value.forEach(s => {
      const key = s.group ?? '未分组';
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key)!.push(s);
    });
    return groups;
  });

  // ---- Actions ----
  function setSessions(list: Session[]) {
    sessions.value = list;
  }

  function createSession(session: Session) {
    sessions.value.push(session);
    activeSessionId.value = session.id;
  }

  function switchSession(sessionId: string) {
    activeSessionId.value = sessionId;
  }

  function closeSession(sessionId: string) {
    sessions.value = sessions.value.filter(s => s.id !== sessionId);
    if (activeSessionId.value === sessionId) {
      activeSessionId.value = sessions.value[0]?.id ?? null;
    }
  }

  function renameSession(sessionId: string, name: string) {
    const session = sessions.value.find(s => s.id === sessionId);
    if (session) session.name = name;
  }

  function setMessages(msgs: ChatMessage[]) {
    messages.value = msgs;
  }

  function appendMessage(msg: ChatMessage) {
    messages.value.push(msg);
  }

  function appendStreamingContent(chunk: string) {
    streamingContent.value += chunk;
  }

  function finalizeStreaming() {
    if (streamingContent.value) {
      messages.value.push({
        id: `msg_${Date.now()}`,
        sessionId: activeSessionId.value ?? '',
        role: 'assistant',
        type: 'text',
        content: streamingContent.value,
        timestamp: Date.now(),
      });
      streamingContent.value = '';
    }
  }

  function setLoading(val: boolean) {
    loading.value = val;
  }

  function setChatMode(mode: ChatMode) {
    chatMode.value = mode;
  }

  return {
    sessions, activeSessionId, messages, loading,
    streamingContent, chatMode,
    activeSession, sessionGroups,
    setSessions, createSession, switchSession,
    closeSession, renameSession,
    setMessages, appendMessage,
    appendStreamingContent, finalizeStreaming,
    setLoading, setChatMode,
  };
});
```
