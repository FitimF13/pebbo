import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  // During development the PC app talks to a locally running `pebbo serve`.
  server: { proxy: { '/api': 'http://127.0.0.1:8100' } },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/network-guard.ts'],
  },
});
