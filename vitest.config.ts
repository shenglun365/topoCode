import { defineConfig } from 'vitest/config';
import { resolve } from 'path';

export default defineConfig({
  test: {
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
      '@topo-animation': resolve(__dirname, 'src/lib/topo-animation'),
    },
  },
});
