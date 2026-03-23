import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig(() => {
  const backendUrl = process.env.VITE_BACKEND_URL || 'http://127.0.0.1:8000';
  const host = process.env.VITE_HOST || '127.0.0.1';
  const port = Number(process.env.VITE_PORT || '5173');

  return {
    plugins: [react()],
    server: {
      host,
      port,
      proxy: {
        '/api': backendUrl,
      },
    },
  };
});
