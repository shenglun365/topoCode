/**
 * Store —— 叙事黑板（C2 裁决落点）
 * vars：叙事状态（guard/编排读取；分支回头时语义延续）
 * 位置两层：committed（编辑模式落库/随导出走） 与 draft（播放模式拖动只进 draft，离开即弃）
 *   effective = draft ?? committed（两模式拖动期间均可预览）；持久化/导出只取 committed。
 */

export interface Offset {
  dx: number;
  dy: number;
}

export type StoryMode = 'play' | 'edit';

export interface PositionLayer {
  /** 整图偏移两层（同 entity 语义：play 拖动进 draft，edit 提交进 committed） */
  effectiveGlobal(): Offset;
  setDraftGlobal(off: Offset | null): void;
  commitDraftGlobal(): void;
  globalCommitted(): Offset;
  /** 当前生效值（draft 优先，供渲染/命中） */
  effective(key: string): Offset | null;
  /** 拖动预览写入（null 清 draft[key]） */
  setDraft(key: string, off: Offset | null): void;
  /** edit 模式：draft → committed（pointerup 即落库；按钮化留待再议） */
  commitDraft(): void;
  /** 弃掉全部 draft（播放模式拖动结束/切状态时调用） */
  discardDraft(): void;
  /** 手动复位某键（两层同清） */
  reset(key: string): void;
  resetAll(): void;
  snapshot(): { committed: Record<string, Offset>; draft: Record<string, Offset>; global: Offset };
  restore(snap: { committed?: Record<string, Offset>; draft?: Record<string, Offset>; global?: Offset }): void;
}

export interface StoryStore {
  mode(): StoryMode;
  setMode(m: StoryMode): void;
  var<T = unknown>(name: string): T | undefined;
  setVar(name: string, value: unknown): void;
  vars(): Record<string, unknown>;
  position: PositionLayer;
  /** 变更订阅（vars/position/mode 均触发；供编译器失效缓存） */
  subscribe(cb: () => void): () => void;
}

export function createStoryStore(init?: {
  vars?: Record<string, unknown>;
  committed?: Record<string, Offset>;
  global?: Offset;
  mode?: StoryMode;
}): StoryStore {
  const vars: Record<string, unknown> = { ...(init?.vars ?? {}) };
  const committed: Record<string, Offset> = { ...(init?.committed ?? {}) };
  const draft: Record<string, Offset> = {};
  let storyMode: StoryMode = init?.mode ?? 'play';
  const subs = new Set<() => void>();
  const bump = (): void => { for (const s of [...subs]) s(); };

  let gCommitted: Offset = init?.global ? { ...init.global } : { dx: 0, dy: 0 };
  let gDraft: Offset | null = null;
  const zero = (): Offset => ({ dx: 0, dy: 0 });
  const position: PositionLayer = {
    effectiveGlobal() {
      const d = gDraft ?? zero();
      return { dx: gCommitted.dx + d.dx, dy: gCommitted.dy + d.dy };
    },
    setDraftGlobal(off) {
      gDraft = off ? { ...off } : null;
      bump();
    },
    commitDraftGlobal() {
      if (gDraft) {
        gCommitted = { dx: gCommitted.dx + gDraft.dx, dy: gCommitted.dy + gDraft.dy };
        gDraft = null;
      }
      bump();
    },
    globalCommitted() { return { ...gCommitted }; },
    effective(key) {
      return draft[key] ?? committed[key] ?? null;
    },
    setDraft(key, off) {
      if (off) draft[key] = { dx: off.dx, dy: off.dy };
      else delete draft[key];
      bump();
    },
    commitDraft() {
      for (const [k, v] of Object.entries(draft)) committed[k] = v;
      for (const k of Object.keys(draft)) delete draft[k];
      bump();
    },
    discardDraft() {
      for (const k of Object.keys(draft)) delete draft[k];
      bump();
    },
    reset(key) {
      delete draft[key];
      delete committed[key];
      bump();
    },
    resetAll() {
      for (const k of Object.keys(draft)) delete draft[k];
      for (const k of Object.keys(committed)) delete committed[k];
      gDraft = null;
      gCommitted = zero();
      bump();
    },
    snapshot() {
      return { committed: { ...committed }, draft: { ...draft }, global: { ...gCommitted } };
    },
    restore(snap) {
      for (const k of Object.keys(committed)) delete committed[k];
      for (const k of Object.keys(draft)) delete draft[k];
      Object.assign(committed, snap.committed ?? {});
      Object.assign(draft, snap.draft ?? {});
      if (snap.global) gCommitted = { ...snap.global };
      bump();
    },
  };

  return {
    mode: () => storyMode,
    setMode(m) { storyMode = m; bump(); },
    var<T>(name: string) { return vars[name] as T | undefined; },
    setVar(name, value) { vars[name] = value; bump(); },
    vars: () => vars,
    position,
    subscribe(cb) {
      subs.add(cb);
      return () => subs.delete(cb);
    },
  };
}
