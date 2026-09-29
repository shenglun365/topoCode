import type { SceneSpec } from '../src/core/types';

export function emptyScene(): SceneSpec {
  return { elements: [], width: 0, height: 0, type: '', backend: '' };
}
