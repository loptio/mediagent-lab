import { defineConfig, devices } from '@playwright/test'

import { BASE_URL } from './support/stack'

/**
 * E2E：docs/requirements.md 第 3 節的三個使用情境。
 * 先用 `pnpm stack:up` 啟動 mock 模式的 Docker Compose 環境（見 README「E2E 測試」）。
 * 測試共用同一個資料庫，依檔名順序一個一個執行。
 */
export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  globalSetup: './support/global-setup.ts',
  use: {
    baseURL: BASE_URL,
    locale: 'zh-TW',
    timezoneId: 'Asia/Taipei',
    // 圖片由 https://localhost:18443（Caddy 自簽憑證）提供
    ignoreHTTPSErrors: true,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})
