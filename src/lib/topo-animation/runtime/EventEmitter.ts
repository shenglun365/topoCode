/**
 * 事件发射器
 * @module runtime/EventEmitter
 */

type EventHandler = (...args: any[]) => void;

export class EventEmitter {
  private events: Map<string, Set<EventHandler>> = new Map();

  /** 订阅事件 */
  on(event: string, handler: EventHandler): void {
    if (!this.events.has(event)) {
      this.events.set(event, new Set());
    }
    this.events.get(event)!.add(handler);
  }

  /** 订阅事件（一次性） */
  once(event: string, handler: EventHandler): void {
    const wrapped = (...args: any[]) => {
      handler(...args);
      this.off(event, wrapped);
    };
    this.on(event, wrapped);
  }

  /** 取消订阅 */
  off(event: string, handler: EventHandler): void {
    this.events.get(event)?.delete(handler);
  }

  /** 触发事件 */
  emit(event: string, ...args: any[]): void {
    const handlers = this.events.get(event);
    if (handlers) {
      for (const handler of handlers) {
        try {
          handler(...args);
        } catch (error) {
          console.error(`Event handler error for '${event}':`, error);
        }
      }
    }
  }

  /** 移除所有监听器 */
  removeAllListeners(event?: string): void {
    if (event) {
      this.events.delete(event);
    } else {
      this.events.clear();
    }
  }

  /** 获取监听器数量 */
  listenerCount(event?: string): number {
    if (event) {
      return this.events.get(event)?.size || 0;
    }
    let count = 0;
    for (const [, handlers] of this.events) {
      count += handlers.size;
    }
    return count;
  }
}
