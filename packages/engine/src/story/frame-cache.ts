/**
 * 帧渲染缓存（集成批 1.3）：源文 → SVG 持久化。
 *
 * 目的：① 重复源文（动画回放、图谱反复切视图、receipt 重跑）零渲染开销；
 * ② 「网页刷新不中断」——刷新后已渲染帧命中缓存秒回，未完成队列由消费方续跑。
 * 后端渲染对同一源文输出确定（mermaid/dot/plantuml 纯函数），缓存永远安全。
 *
 * 环境无 IndexedDB（node/测试）自动降级进程内 LRU；一切 IDB 异常静默（缓存是加速器不是真相）。
 */

import { fnv1a } from '../core/key';

export interface FrameCache {
  get(key: string): Promise<string | null>;
  put(key: string, svg: string): Promise<void>;
  clear?(): Promise<void>;
}

/** 缓存键：后端 id + 源文指纹（trim 归一） */
export function frameCacheKey(backendId: string, source: string): string {
  return `${backendId}:${fnv1a(source.trim())}`;
}

/* ============ 内存 LRU（降级实现/测试用） ============ */

export function createMemoryFrameCache(limit = 64): FrameCache {
  const map = new Map<string, string>();
  return {
    async get(key) {
      const v = map.get(key);
      if (v !== undefined) { map.delete(key); map.set(key, v); } // LRU 触活
      return v ?? null;
    },
    async put(key, svg) {
      map.delete(key);
      map.set(key, svg);
      while (map.size > limit) map.delete(map.keys().next().value as string);
    },
    async clear() { map.clear(); },
  };
}

/* ============ IndexedDB（浏览器主实现） ============ */

interface IdbRecord { svg: string; ts: number }

export function createIdbFrameCache(namespace = 'ta-frame-cache'): FrameCache {
  if (typeof indexedDB === 'undefined') return createMemoryFrameCache();
  let dbP: Promise<IDBDatabase | null> | null = null;
  const db = (): Promise<IDBDatabase | null> => {
    dbP ??= new Promise<IDBDatabase | null>((res) => {
      try {
        const req = indexedDB.open(namespace, 1);
        req.onupgradeneeded = (): void => {
          if (!req.result.objectStoreNames.contains('frames')) req.result.createObjectStore('frames');
        };
        req.onsuccess = (): void => res(req.result);
        req.onerror = (): void => res(null);
        setTimeout(() => res(null), 2000); // 打开超时 → 静默降级
      } catch { res(null); }
    });
    return dbP;
  };
  return {
    async get(key) {
      const d = await db();
      if (!d) return null;
      return new Promise((res) => {
        try {
          const r = d.transaction('frames', 'readonly').objectStore('frames').get(key) as IDBRequest<IdbRecord | undefined>;
          r.onsuccess = (): void => res(r.result?.svg ?? null);
          r.onerror = (): void => res(null);
        } catch { res(null); }
      });
    },
    async put(key, svg) {
      const d = await db();
      if (!d) return;
      try { d.transaction('frames', 'readwrite').objectStore('frames').put({ svg, ts: Date.now() } as IdbRecord, key); } catch { /* 静默 */ }
    },
    async clear() {
      const d = await db();
      if (!d) return;
      try { d.transaction('frames', 'readwrite').objectStore('frames').clear(); } catch { /* 静默 */ }
    },
  };
}

/** 默认工厂：浏览器 → IDB，其余 → 内存 */
export function createFrameCache(namespace?: string): FrameCache {
  return typeof indexedDB === 'undefined' ? createMemoryFrameCache() : createIdbFrameCache(namespace);
}
