import { beforeEach, describe, expect, it, vi } from 'vitest';
import { PlantUmlEngine } from '../../src/topoOne/engines/plantuml/plantuml';

const SVG_OK =
  '<svg xmlns="http://www.w3.org/2000/svg"><g id="part1" data-entity-uid="part1" data-source-line="1"><title>Alice</title></g></svg>';
const SVG_ERR =
  '<svg xmlns="http://www.w3.org/2000/svg"><text>Syntax Error?</text><text>(Assumed diagram type: sequence)</text></svg>';

function mockFetch(status: number, body: string) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({ status, ok: status < 400, text: async () => body }),
  );
}

describe('PlantUmlEngine', () => {
  beforeEach(() => vi.unstubAllGlobals());

  it('renders via GET /svg/{encoded} and keeps data-entity attrs', async () => {
    mockFetch(200, SVG_OK);
    const engine = new PlantUmlEngine({ baseUrl: 'http://test' });
    const res = await engine.render({
      container: document.createElement('div'),
      code: '@startuml\nA\n@enduml',
    });
    expect(res.svg).toContain('data-entity-uid');
    const url = vi.mocked(fetch).mock.calls[0][0] as string;
    expect(url).toMatch(/^http:\/\/test\/svg\//);
  });

  it('detects syntax error via HTTP 400', async () => {
    mockFetch(400, SVG_ERR);
    const engine = new PlantUmlEngine({ baseUrl: 'http://test' });
    const v = await engine.validate('@startuml\n???');
    expect(v.valid).toBe(false);
    expect(v.error).toContain('Syntax Error');
  });

  it('treats HTTP 302 as invalid', async () => {
    mockFetch(302, '');
    const engine = new PlantUmlEngine({ baseUrl: 'http://test' });
    const v = await engine.validate('@startsequence\nA\n@enduml');
    expect(v.valid).toBe(false);
  });
});
