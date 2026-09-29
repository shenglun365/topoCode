import { describe, expect, it } from 'vitest';
import {
  commandsEqual, commandsToD, isomorphicPaths, lerpCommands, parsePathD, pathBbox, shapesToCommands, translateCommands,
} from '../src/core/path';

describe('parsePathD', () => {
  it('解析绝对坐标基本指令', () => {
    const cmds = parsePathD('M 10 20 L 30 40 Z');
    expect(cmds).toEqual([
      { c: 'M', x: 10, y: 20 },
      { c: 'L', x: 30, y: 40 },
      { c: 'Z' },
    ]);
  });

  it('相对指令 m/l 转为绝对', () => {
    const cmds = parsePathD('m 10 10 l 5 5 l 5 5');
    expect(cmds).toEqual([
      { c: 'M', x: 10, y: 10 },
      { c: 'L', x: 15, y: 15 },
      { c: 'L', x: 20, y: 20 },
    ]);
  });

  it('H/V 归一化为 L', () => {
    const cmds = parsePathD('M 0 0 H 10 V 10');
    expect(cmds).toEqual([
      { c: 'M', x: 0, y: 0 },
      { c: 'L', x: 10, y: 0 },
      { c: 'L', x: 10, y: 10 },
    ]);
  });

  it('隐式重复参数（L 后连续坐标对）', () => {
    const cmds = parsePathD('M 0 0 5 5 10 10');
    expect(cmds.map((c) => c.c)).toEqual(['M', 'L', 'L']);
  });

  it('S 平滑曲线反射控制点', () => {
    const cmds = parsePathD('M 0 0 C 0 10 10 10 10 0 S 20 -10 20 0');
    expect(cmds[1]!.c).toBe('C');
    const c2 = cmds[2] as { c: 'C'; x1: number; y1: number };
    expect(c2.x1).toBe(10); // 反射 (10,10) 关于 (10,0)
    expect(c2.y1).toBe(-10);
  });

  it('A 弧线参数（分隔符隔开）', () => {
    const cmds = parsePathD('M 0 0 A 25 25 0 0 1 50 0');
    expect(cmds[1]).toEqual({ c: 'A', rx: 25, ry: 25, rot: 0, laf: 0, sf: 1, x: 50, y: 0 });
  });

  it('负数与无逗号科学计数', () => {
    const cmds = parsePathD('M-10.5-20L1e2-30');
    expect(cmds).toEqual([
      { c: 'M', x: -10.5, y: -20 },
      { c: 'L', x: 100, y: -30 },
    ]);
  });
});

describe('测量与变换', () => {
  it('pathBbox 直线', () => {
    expect(pathBbox(parsePathD('M 10 20 L 30 40'))).toEqual({ x: 10, y: 20, width: 20, height: 20 });
  });

  it('pathBbox 含曲线采样', () => {
    const b = pathBbox(parsePathD('M 0 0 C 10 100 90 100 100 0'));
    expect(b.y).toBeLessThanOrEqual(0);
    expect(b.height).toBeGreaterThan(40);
    expect(b.x).toBeCloseTo(0, 0);
    expect(b.width).toBeCloseTo(100, 0);
  });

  it('translateCommands', () => {
    const t = translateCommands(parsePathD('M 0 0 L 10 10'), 5, -5);
    expect(t).toEqual([
      { c: 'M', x: 5, y: -5 },
      { c: 'L', x: 15, y: 5 },
    ]);
  });

  it('commandsEqual 容差', () => {
    expect(commandsEqual(parsePathD('M 0 0 L 10 10'), parsePathD('M 0.3 0 L 10 10'))).toBe(true);
    expect(commandsEqual(parsePathD('M 0 0 L 10 10'), parsePathD('M 2 0 L 10 10'))).toBe(false);
    expect(commandsEqual(parsePathD('M 0 0 L 10 10'), parsePathD('M 0 0 L 10 10 Z'))).toBe(false);
  });
});

describe('shapesToCommands', () => {
  it('rect -> 闭合折线', () => {
    const cmds = shapesToCommands('rect', { x: '1', y: '2', width: '10', height: '20' });
    expect(cmds.map((c) => c.c)).toEqual(['M', 'L', 'L', 'L', 'Z']);
    expect(pathBbox(cmds)).toEqual({ x: 1, y: 2, width: 10, height: 20 });
  });

  it('circle -> 双弧', () => {
    const cmds = shapesToCommands('circle', { cx: '50', cy: '50', r: '10' });
    expect(cmds.map((c) => c.c)).toEqual(['M', 'A', 'A', 'Z']);
  });

  it('polygon 闭合、polyline 不闭合', () => {
    expect(shapesToCommands('polygon', { points: '0,0 10,0 10,10' }).at(-1)!.c).toBe('Z');
    expect(shapesToCommands('polyline', { points: '0,0 10,0 10,10' }).at(-1)!.c).toBe('L');
  });
});

describe('同构判定与插值', () => {
  it('isomorphicPaths 类型序列一致才可插值', () => {
    expect(isomorphicPaths(parsePathD('M 0 0 L 10 10'), parsePathD('M 5 5 L 20 20'))).toBe(true);
    expect(isomorphicPaths(parsePathD('M 0 0 L 10 10'), parsePathD('M 0 0 C 1 1 2 2 3 3'))).toBe(false);
  });

  it('lerpCommands 端点收敛', () => {
    const a = parsePathD('M 0 0 L 10 10');
    const b = parsePathD('M 2 2 L 20 20');
    expect(lerpCommands(a, b, 0)).toEqual(a);
    expect(lerpCommands(a, b, 1)).toEqual(b);
    const mid = lerpCommands(a, b, 0.5);
    expect((mid[0] as { x: number }).x).toBe(1);
  });

  it('commandsToD 往返解析稳定', () => {
    const cmds = parsePathD('M 1 2 C 3 4 5 6 7 8 Q 9 10 11 12 Z');
    const reparsed = parsePathD(commandsToD(cmds));
    expect(commandsEqual(cmds, reparsed, 0.01)).toBe(true);
  });
});
