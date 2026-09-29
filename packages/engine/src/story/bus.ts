/** 极简同步事件总线：叙事引擎对外交互入口（renderer 语义命中事件/宿主 dispatch 共用） */
export type EventHandler = (event: string, payload?: unknown) => void;

export interface EventBus {
  emit(event: string, payload?: unknown): void;
  subscribe(handler: EventHandler): () => void;
}

export function createEventBus(): EventBus {
  const handlers = new Set<EventHandler>();
  return {
    emit(event, payload) {
      for (const h of [...handlers]) h(event, payload);
    },
    subscribe(h) {
      handlers.add(h);
      return () => handlers.delete(h);
    },
  };
}
