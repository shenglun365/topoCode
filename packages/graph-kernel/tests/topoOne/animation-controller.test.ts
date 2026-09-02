import { afterEach, describe, expect, it, vi } from 'vitest';
import { createAnimationController } from '../../src/topoOne/animation/controller';
import type { AnimationPlan } from '../../src/topoOne/animation/types';

function makeEls(n: number): Element[] {
  const out: Element[] = [];
  for (let i = 0; i < n; i++) {
    const el = document.createElement('div');
    el.id = `el-${i}`;
    document.body.appendChild(el);
    out.push(el);
  }
  return out;
}

function makePlan(mode: AnimationPlan["mode"], stepCount: number, stepMs = 100): { plan: AnimationPlan; els: Element[] } {
  const els = makeEls(stepCount);
  return {
    plan: { mode, stepMs, steps: els.map((el, i) => ({ label: `s${i}`, elements: [el] })) },
    els,
  };
}

afterEach(() => {
  document.body.innerHTML = '';
  vi.useRealTimers();
});

describe('animation controller (reveal)', () => {
  it('hides all step elements initially', () => {
    vi.useFakeTimers();
    const { plan, els } = makePlan('reveal', 3);
    const c = createAnimationController({ plan });
    expect(c.index).toBe(-1);
    for (const el of els) expect(el.classList.contains('td-anim-hidden')).toBe(true);
    c.dispose();
  });

  it('plays through all steps at the configured cadence', () => {
    vi.useFakeTimers();
    const { plan, els } = makePlan('reveal', 3, 100);
    const c = createAnimationController({ plan });
    c.play();
    expect(c.playing).toBe(true);
    vi.advanceTimersByTime(100);
    expect(c.index).toBe(0);
    expect(els[0].classList.contains('td-anim-hidden')).toBe(false);
    expect(els[1].classList.contains('td-anim-hidden')).toBe(true);
    vi.advanceTimersByTime(200);
    expect(c.index).toBe(2);
    vi.advanceTimersByTime(100);
    expect(c.playing).toBe(false);
    c.dispose();
  });

  it('pause stops, next/prev/seek step manually, stop resets to hidden', () => {
    vi.useFakeTimers();
    const { plan, els } = makePlan('reveal', 3, 100);
    const c = createAnimationController({ plan });
    c.play();
    vi.advanceTimersByTime(100);
    c.pause();
    vi.advanceTimersByTime(1000);
    expect(c.index).toBe(0);
    expect(c.playing).toBe(false);

    c.next();
    expect(c.index).toBe(1);
    c.prev();
    expect(c.index).toBe(0);
    c.seek(2);
    expect(c.index).toBe(2);
    expect(els[2].classList.contains('td-anim-hidden')).toBe(false);

    c.stop();
    expect(c.index).toBe(-1);
    for (const el of els) expect(el.classList.contains('td-anim-hidden')).toBe(true);
    c.dispose();
  });

  it('replay from the end restarts at step 0', () => {
    vi.useFakeTimers();
    const { plan, els } = makePlan('reveal', 2, 100);
    const c = createAnimationController({ plan });
    c.seek(1);
    c.play();
    vi.advanceTimersByTime(100);
    expect(c.index).toBe(0);
    expect(els[0].classList.contains('td-anim-hidden')).toBe(false);
    c.dispose();
  });

  it('setSpeed changes the cadence', () => {
    vi.useFakeTimers();
    const { plan } = makePlan('reveal', 3, 100);
    const c = createAnimationController({ plan });
    c.setSpeed(2);
    c.play();
    vi.advanceTimersByTime(50);
    expect(c.index).toBe(0);
    c.dispose();
  });

  it('subscribe receives state changes; dispose clears classes and listeners', () => {
    vi.useFakeTimers();
    const { plan, els } = makePlan('reveal', 2, 100);
    const c = createAnimationController({ plan });
    const seen: number[] = [];
    c.subscribe((s) => seen.push(s.index));
    c.next();
    c.dispose();
    for (const el of els) {
      expect(el.classList.contains('td-anim-el')).toBe(false);
      expect(el.classList.contains('td-anim-hidden')).toBe(false);
    }
    expect(seen).toEqual([-1, 0]);
  });
});

describe('animation controller (highlight)', () => {
  it('keeps all elements visible and marks only the active step', () => {
    vi.useFakeTimers();
    const { plan, els } = makePlan('highlight', 3, 100);
    const c = createAnimationController({ plan });
    c.next();
    expect(els[0].classList.contains('td-anim-hidden')).toBe(false);
    expect(els[0].classList.contains('td-anim-active')).toBe(true);
    expect(els[1].classList.contains('td-anim-active')).toBe(false);
    c.next();
    expect(els[0].classList.contains('td-anim-active')).toBe(false);
    expect(els[1].classList.contains('td-anim-active')).toBe(true);
    c.dispose();
  });
});
