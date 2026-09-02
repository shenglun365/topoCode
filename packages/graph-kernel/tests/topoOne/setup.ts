import { beforeAll } from 'vitest';

/**
 * jsdom does not implement SVG getBBox; mermaid's dagre layout calls it to measure nodes.
 * A small non-zero stub is enough for render smoke tests (layout fidelity is not asserted).
 */
beforeAll(() => {
  const proto = SVGElement.prototype as unknown as { getBBox?: unknown };
  if (typeof SVGElement !== 'undefined' && !proto.getBBox) {
    proto.getBBox = () => ({ x: 0, y: 0, width: 10, height: 10 });
  }
});
