import { describe, expect, it } from 'vitest';
import {
  createScheduler, createEventBus, createStoryStore, createDebugRenderer,
  placeholderCompiler, validateGraph,
  type StateGraphSpec,
} from '../src/story';
import { settle } from './fixtures';

const st = (...ids: string[]) => ids.map((id) => ({ id, svg: `<svg xmlns="http://www.w3.org/2000/svg"/>` }));

const wait = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms));

describe('StateGraph 校验', () => {
  it('entry 缺失 / 边悬空 / 多出边', () => {
    expect(validateGraph({ entry: 'x', states: st('a'), edges: [] })).toHaveLength(1);
    expect(validateGraph({ entry: 'a', states: st('a'), edges: [{ from: 'a', to: 'zz' }] })).toHaveLength(1);
    expect(validateGraph({
      entry: 'a', states: st('a', 'b', 'c'),
      edges: [
        { from: 'a', to: 'b' },
        { from: 'a', to: 'c' },
      ],
    })).toHaveLength(1);
  });

  it('非法图 start() 抛错', async () => {
    const sch = createScheduler({
      graph: { entry: 'nope', states: st('a'), edges: [] },
      compiler: placeholderCompiler(), renderer: createDebugRenderer(),
    });
    await expect(sch.start()).rejects.toThrow(/invalid graph/);
  });
});

describe('Scheduler —— 线性帧序列（驻留/手动/跳转）', () => {
  it('链状图纯自动 = dwell 0 退化；末帧无出边 → ended', async () => {
    const graph: StateGraphSpec = {
      entry: 'a',
      states: [{ id: 'a', svg: '', dwellMs: 0 }, { id: 'b', svg: '', dwellMs: 0 }, { id: 'c', svg: '', dwellMs: 0 }],
      edges: [
        { from: 'a', to: 'b', choreography: { durationMs: 5 } },
        { from: 'b', to: 'c' },
      ],
    };
    const rd = createDebugRenderer();
    const sch = createScheduler({ graph, compiler: placeholderCompiler(5), renderer: rd });
    await sch.start();
    expect(rd.history).toEqual(['a', 'b', 'c']);
    expect(sch.snapshot.phase).toBe('ended');
  });

  it('dwell 计时驻留：每帧 HOLD step 毫秒后推进', async () => {
    const graph: StateGraphSpec = {
      entry: 'a',
      states: [{ id: 'a', svg: '', dwellMs: 60 }, { id: 'b', svg: '', dwellMs: 60 }, { id: 'c', svg: '', dwellMs: 0 }],
      edges: [{ from: 'a', to: 'b' }, { from: 'b', to: 'c' }],
    };
    const rd = createDebugRenderer();
    const sch = createScheduler({ graph, compiler: placeholderCompiler(1), renderer: rd });
    const t0 = Date.now();
    await sch.start();
    expect(rd.history).toEqual(['a', 'b', 'c']);
    expect(Date.now() - t0).toBeGreaterThanOrEqual(100);
  });

  it('dwell=0 首帧无限 HOLD 等手动 next；next 逐步推进', async () => {
    const graph: StateGraphSpec = {
      entry: 'a', states: st('a', 'b', 'c'),
      edges: [{ from: 'a', to: 'b' }, { from: 'b', to: 'c' }],
    };
    const rd = createDebugRenderer();
    const sch = createScheduler({ graph, compiler: placeholderCompiler(1), renderer: rd });
    const run = sch.start();
    await settle(() => sch.snapshot.phase === 'hold', 3000, '进入 hold');
    expect(rd.history).toEqual(['a']);
    sch.next();
    await settle(() => sch.snapshot.phase === 'hold' && rd.history.length === 2, 3000, 'b hold');
    sch.next();
    await settle(() => sch.snapshot.phase === 'hold' && rd.history.length === 3, 3000, 'c hold');
    sch.next(); // 末帧（手动）：next 收尾
    await run;
    expect(rd.history).toEqual(['a', 'b', 'c']);
  });

  it('EXECUTING 期间 next 不打断过渡，于下一 HOLD 头消费（重复 next 合并）', async () => {
    const graph: StateGraphSpec = {
      entry: 'a',
      states: [{ id: 'a', svg: '', dwellMs: 0 }, { id: 'x', svg: '', dwellMs: 0 }, { id: 'y', svg: '', dwellMs: 0 }],
      edges: [
        { from: 'a', to: 'x', choreography: { durationMs: 1 } },
        { from: 'x', to: 'y', choreography: { durationMs: 1 } },
      ],
    };
    const rd = createDebugRenderer();
    const sch = createScheduler({ graph, compiler: placeholderCompiler(150), renderer: rd });
    const run = sch.start();
    await settle(() => sch.snapshot.phase === 'executing', 3000, 'a executing');
    sch.next();
    sch.next(); // 重复挂起被合并（pendingJump 只记一次）
    expect(rd.history).toEqual(['a']); // 未打断当前 plan
    await run;
    expect(rd.history).toEqual(['a', 'x', 'y']); // 挂起的一步于 a 的 HOLD 头消费后自动链推进
  });

  it('stepLimit 保护（自环）；stop() 可从无限 HOLD 唤醒', async () => {
    const graph: StateGraphSpec = {
      entry: 'a', states: [{ id: 'a', svg: '', dwellMs: 0 }],
      edges: [{ from: 'a', to: 'a' }],
    };
    void 0;
    const rd = createDebugRenderer();
    const errors: Error[] = [];
    const sch = createScheduler({
      graph, compiler: placeholderCompiler(1), renderer: rd, stepLimit: 5,
      onError: (e) => { errors.push(e); },
    });
    await sch.start();
    expect(errors[0]?.message).toMatch(/stepLimit/);
    expect(sch.snapshot.phase).toBe('ended');

    const g2: StateGraphSpec = {
      entry: 'a', states: st('a', 'x'),
      edges: [{ from: 'a', to: 'x' }],
    };
    const sch2 = createScheduler({ graph: g2, compiler: placeholderCompiler(1), renderer: createDebugRenderer() });
    void sch2.start();
    await settle(() => sch2.snapshot.phase === 'hold', 3000, '进入 hold'); // 无 dwell → 无限 HOLD
    sch2.stop();
    expect(sch2.snapshot.phase).toBe('stopped');
  });

  it('store 两层位置：draft 预览优先、commit/discard、持久层独立（C2）', () => {
    const s = createStoryStore({ committed: { A: { dx: 10, dy: 0 } } });
    expect(s.position.effective('A')).toEqual({ dx: 10, dy: 0 });
    s.position.setDraft('A', { dx: 99, dy: 5 });
    expect(s.position.effective('A')).toEqual({ dx: 99, dy: 5 }); // 拖动期间两模式均可见 draft
    s.setMode('edit');
    s.position.commitDraft();
    expect(s.position.effective('A')).toEqual({ dx: 99, dy: 5 });
    s.position.setDraft('A', null);
    expect(s.position.effective('A')).toEqual({ dx: 99, dy: 5 }); // committed 仍在
    s.position.discardDraft();
    s.position.reset('A');
    expect(s.position.effective('A')).toBeNull();
    // play 模式：拖动进 draft，离开即弃，committed 不受污染
    s.position.setDraft('B', { dx: 3, dy: 3 });
    s.setMode('play');
    s.position.discardDraft();
    expect(s.position.snapshot().committed.B).toBeUndefined();
    // 序列化/恢复（随导出包走的是 committed）
    const snap = JSON.parse(JSON.stringify({ ...s.position.snapshot(), committed: { C: { dx: 1, dy: 2 } }, draft: {} }));
    s.position.restore(snap);
    expect(s.position.effective('C')).toEqual({ dx: 1, dy: 2 });
    expect(s.var('missing')).toBeUndefined();
    s.setVar('round', 2);
    expect(s.var('round')).toBe(2);
  });
});

describe('Scheduler pause/goto（调试与播放控制）', () => {
  it('goto：hold 中立即跳转任意帧（跳过中间帧）', async () => {
    const graph: StateGraphSpec = {
      entry: 'a', states: st('a', 'b', 'c'),
      edges: [{ from: 'a', to: 'b' }, { from: 'b', to: 'c' }],
    };
    const rd = createDebugRenderer();
    const sch = createScheduler({ graph, compiler: placeholderCompiler(1), renderer: rd });
    const run = sch.start();
    await settle(() => sch.snapshot.phase === 'hold', 3000, 'a hold');
    sch.goto('c');
    sch.next(); // c 为手动末帧：next 收尾
    await run;
    expect(rd.history).toEqual(['a', 'c']); // b 未被访问；c 无出边 → ended
    expect(sch.snapshot.phase).toBe('ended');
  });

  it('pause 冻结驻留计时；resume 续剩余并消费暂停期 next', async () => {
    const graph: StateGraphSpec = {
      entry: 'a',
      states: [{ id: 'a', svg: '', dwellMs: 80 }, { id: 'b', svg: '', dwellMs: 0 }, { id: 'y', svg: '' }],
      edges: [{ from: 'a', to: 'b' }, { from: 'a', to: 'y' }],
    };
    // a 两条出边 → 校验拒；改单链：a → x(dwell80) → y
    const g: StateGraphSpec = {
      entry: 'a',
      states: [{ id: 'a', svg: '', dwellMs: 80 }, { id: 'x', svg: '' }],
      edges: [{ from: 'a', to: 'x' }],
    };
    const rd = createDebugRenderer();
    const bus = createEventBus();
    const sch = createScheduler({ graph: g, compiler: placeholderCompiler(1), renderer: rd, bus });
    const run = sch.start();
    await wait(20); // 已进入 hold（remaining≈60）
    sch.pause();
    sch.next(); // 暂停期 next → 挂起
    await wait(100); // 超时也不该走
    expect(sch.snapshot.phase).toBe('paused');
    sch.resume(); // resume 消费挂起 → 进 x
    await settle(() => sch.snapshot.phase === 'hold' && sch.snapshot.nodeId === 'x', 3000, 'x hold');
    sch.next(); // 末帧（手动）：next 收尾
    await run;
    expect(rd.history).toEqual(['a', 'x']);
  });

  it('store 整图两层：effectiveGlobal = committed+draft 合成；commit 归位', () => {
    const s = createStoryStore({ global: { dx: 10, dy: 0 } });
    expect(s.position.effectiveGlobal()).toEqual({ dx: 10, dy: 0 });
    s.position.setDraftGlobal({ dx: 5, dy: -5 });
    expect(s.position.effectiveGlobal()).toEqual({ dx: 15, dy: -5 });
    s.position.commitDraftGlobal();
    expect(s.position.effectiveGlobal()).toEqual({ dx: 15, dy: -5 });
    expect(s.position.globalCommitted()).toEqual({ dx: 15, dy: -5 });
    s.position.setDraftGlobal(null);
    expect(s.position.effectiveGlobal()).toEqual({ dx: 15, dy: -5 });
    s.position.resetAll();
    expect(s.position.effectiveGlobal()).toEqual({ dx: 0, dy: 0 });
  });
});
