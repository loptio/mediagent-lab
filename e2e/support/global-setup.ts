import { BASE_URL, seedUsers } from './stack'

/** 確認測試環境已啟動，並建立三種角色的種子使用者（可重複執行） */
export default async function globalSetup(): Promise<void> {
  const health = await fetch(`${BASE_URL}/health`).catch(() => null)
  if (!health?.ok) {
    throw new Error(`E2E 環境沒有啟動（${BASE_URL}）。請先在 e2e/ 執行 pnpm stack:up`)
  }
  seedUsers()
}
