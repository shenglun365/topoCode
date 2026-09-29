import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'jsdom',
    include: ['test/**/*.test.ts'],
    // jsdom 定时器在 17 文件并发下有秒级拉伸，放宽超时避免边界误报
    testTimeout: 15000,
  },
});
