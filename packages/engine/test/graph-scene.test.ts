/** graph-scene —— 统一图 JSON → elk 布局 → 存在性投影 单测 */
import { describe, expect, it } from 'vitest';
import { buildGraphScene, type GraphFrameDataInput } from '../src/core/graph-scene';

const input: GraphFrameDataInput = {
  canonical: {
    nodes: [
      { key: 'api', label: 'api-gateway' },
      { key: 'svc', label: 'user-service', container: 'core' },
      { key: 'db', label: 'postgres', container: 'core' },
      { key: 'web', label: 'web-app' },
    ],
    edges: [
      { from: 'api', to: 'svc' },
      { from: 'svc', to: 'db', key: 'svc->db' },
      { from: 'web', to: 'api' },
    ],
    containers: [{ key: 'core', label: 'core-layer' }],
  },
  frames: [
    { id: 'f1', label: 'initial', nodes: ['api', 'svc', 'db'], edges: ['api->svc', 'svc->db'] },
    { id: 'f2', label: 'add web', nodes: ['api', 'svc', 'db', 'web'], edges: ['api->svc', 'svc->db', 'web->api'], modified: ['svc'] },
    { id: 'f3', label: 'drop db', nodes: ['api', 'svc', 'web'], edges: ['api->svc', 'web->api'] },
  ],
};

describe('buildGraphScene', () => {
  it('布局产出全部 canonical 元素且坐标有效', async () => {
    const g = await buildGraphScene(input);
    expect(g.spec.elements.filter((e) => e.kind === 'node')).toHaveLength(4);
    expect(g.spec.elements.filter((e) => e.kind === 'edge')).toHaveLength(3);
    expect(g.spec.elements.filter((e) => e.kind === 'group')).toHaveLength(1);
    expect(g.spec.width).toBeGreaterThan(0);
    expect(g.spec.height).toBeGreaterThan(0);
    for (const n of g.spec.elements.filter((e) => e.kind === 'node')) {
      expect(n.bbox.width).toBeGreaterThan(0);
      expect(n.bbox.height).toBeGreaterThan(0);
      expect(n.text[0]!.content).toBeTruthy();
      // 节点须落在画布内
      expect(n.bbox.x).toBeGreaterThanOrEqual(-1);
      expect(n.bbox.y).toBeGreaterThanOrEqual(-1);
      expect(n.bbox.x + n.bbox.width).toBeLessThanOrEqual(g.spec.width + 1);
    }
  });

  it('容器包含成员且边端点/路径有效', async () => {
    const g = await buildGraphScene(input);
    const core = g.spec.elements.find((e) => e.key === 'core')!;
    for (const k of ['svc', 'db']) {
      const m = g.spec.elements.find((e) => e.key === k)!;
      // 成员中心落在容器 bbox 内
      const cx = m.bbox.x + m.bbox.width / 2;
      const cy = m.bbox.y + m.bbox.height / 2;
      expect(cx).toBeGreaterThanOrEqual(core.bbox.x);
      expect(cx).toBeLessThanOrEqual(core.bbox.x + core.bbox.width);
      expect(cy).toBeGreaterThanOrEqual(core.bbox.y);
    }
    const e = g.spec.elements.find((el) => el.key === 'api->svc')!;
    expect(e.kind).toBe('edge');
    expect(e.endpoints).toEqual({ from: 'api', to: 'svc' });
    expect(e.paths[0]!.d.length).toBeGreaterThanOrEqual(2);
    // 至少 2 条 path: 折线 + 箭头
    expect(e.paths.length).toBe(2);
  });

  it('存在性投影: 边依赖两端节点、modified 过滤、has 集合精确', async () => {
    const g = await buildGraphScene(input);
    const [f1, f2, f3] = g.frames;
    // f1: 无 web —— web->api 边不得存在
    expect(f1!.has.has('web')).toBe(false);
    expect(f1!.has.has('web->api')).toBe(false);
    expect(f1!.has.has('api->svc')).toBe(true);
    expect(f1!.has.has('svc->db')).toBe(true);
    // f2: 全量 + modified
    expect(f2!.has.has('web->api')).toBe(true);
    expect(f2!.modified.has('svc')).toBe(true);
    // f3: db 消失 → svc->db 边连带消失
    expect(f3!.has.has('db')).toBe(false);
    expect(f3!.has.has('svc->db')).toBe(false);
    // 标签
    expect(f2!.label).toBe('add web');
  });

  it('同一输入布局确定性(两次调用坐标一致)', async () => {
    const a = await buildGraphScene(input);
    const b = await buildGraphScene(input);
    const ka = a.spec.elements.map((e) => `${e.key}:${Math.round(e.bbox.x)},${Math.round(e.bbox.y)}`).sort();
    const kb = b.spec.elements.map((e) => `${e.key}:${Math.round(e.bbox.x)},${Math.round(e.bbox.y)}`).sort();
    expect(ka).toEqual(kb);
  });
});
