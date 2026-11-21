import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
    // The same guard as the web app: tests may only reach loopback (docs/development.md).
    setupFiles: ['../web/src/test/network-guard.ts'],
  },
});
