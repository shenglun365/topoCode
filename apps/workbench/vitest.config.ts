import { defineConfig } from 'vitest/config';
import { resolve } from 'path';

export default defineConfig({
  test: {
    // M10: web-core 测试已迁 packages/web-core（由 web-core 自身 vitest 运行）
    include: ['tests/**/*.test.ts'],
    environment: 'jsdom',
    globals: true,
    coverage: {
      provider: 'v8',
      include: ['src/utils/**', 'src/services/**', 'src/stores/**'],
    },
  },
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
          },
  },
});
