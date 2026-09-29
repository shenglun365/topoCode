import type { SceneSpec } from './types';

/** 空场景（diff 起点/entry 全入场的基准） */
export function emptySceneSpec(): SceneSpec {
  return { elements: [], width: 0, height: 0, type: '', backend: '' };
}
