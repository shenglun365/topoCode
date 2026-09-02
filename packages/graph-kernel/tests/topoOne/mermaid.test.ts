import { describe, expect, it, vi } from 'vitest';
import mermaid from 'mermaid';
import { MermaidEngine } from '../../src/engines/mermaid/mermaid';

describe('MermaidEngine (jsdom)', () => {
  it('renders a flowchart to svg', async () => {
    const engine = new MermaidEngine();
    const res = await engine.render({
      container: document.createElement('div'),
      code: 'flowchart TD\n  A[Start] --> B{OK?}\n  B -->|yes| C[Done]',
    });
    expect(res.svg).toContain('<svg');
  });

  it('passes securityLevel and themeVariables to mermaid.initialize', async () => {
    const spy = vi.spyOn(mermaid, 'initialize');
    try {
      const engine = new MermaidEngine();
      await engine.render({
        container: document.createElement('div'),
        code: 'flowchart TD\n  A --> B',
        securityLevel: 'loose',
        themeVariables: { primaryColor: '#1e1e2e', primaryTextColor: '#cdd6f4' },
      });
      const args = spy.mock.calls.at(-1)?.[0] as Record<string, unknown>;
      expect(args.securityLevel).toBe('loose');
      expect(args.themeVariables).toEqual({ primaryColor: '#1e1e2e', primaryTextColor: '#cdd6f4' });
    } finally {
      spy.mockRestore();
    }
  });

  it('defaults to strict securityLevel when omitted', async () => {
    const spy = vi.spyOn(mermaid, 'initialize');
    try {
      const engine = new MermaidEngine();
      await engine.render({ container: document.createElement('div'), code: 'flowchart TD\n  A --> B' });
      expect((spy.mock.calls.at(-1)?.[0] as Record<string, unknown>).securityLevel).toBe('strict');
    } finally {
      spy.mockRestore();
    }
  });

  it('validates good and bad code', async () => {
    const engine = new MermaidEngine();
    const ok = await engine.validate('flowchart TD\n  A --> B');
    expect(ok.valid).toBe(true);
    const bad = await engine.validate('flowchart TD\n  A -->');
    expect(bad.valid).toBe(false);
    expect(bad.error).toBeTruthy();
  });
});
