import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const apiProxyTarget = 'http://127.0.0.1:8000';

function manualChunks(id: string): string | undefined {
  const normalized = id.replace(/\\/g, '/');
  if (!normalized.includes('/node_modules/')) {
    return undefined;
  }
  if (normalized.includes('/@xyflow/')) {
    return 'vendor-flow';
  }
  if (normalized.includes('/lucide-react/')) {
    return 'vendor-icons';
  }
  return 'vendor';
}

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks,
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/v1': {
        target: apiProxyTarget,
        changeOrigin: true,
      },
      '/api': {
        target: apiProxyTarget,
        changeOrigin: true,
      },
      '/registry': {
        target: apiProxyTarget,
        changeOrigin: true,
      },
    },
  },
});
