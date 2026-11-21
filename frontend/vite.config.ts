import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'

// 同源部署（foundation-plan D-06）：建置後的靜態檔由 FastAPI 在 / 提供；
// 本機開發時由 Vite 把 /api 轉給後端，瀏覽器看到的一樣是同一個來源。
const apiTarget = process.env.VITE_API_TARGET ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: apiTarget, changeOrigin: true },
    },
  },
  build: {
    // Element Plus 整包約 1 MB，拆成獨立檔案讓瀏覽器可以長期快取
    chunkSizeWarningLimit: 1200,
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [{ name: 'element-plus', test: /node_modules[\\/](element-plus|@element-plus)/ }],
        },
      },
    },
  },
  test: {
    include: ['src/**/*.test.ts'],
  },
})
