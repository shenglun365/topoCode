/** 交付包运行时入口（esbuild bundle → dist/story-runtime.mjs，HTML 单包内联用） */
export { createStoryEngine, type StoryEngine } from './engine';
export { createStoryStore } from './store';
