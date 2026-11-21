/**
 * 操作 E2E 用的 Docker Compose 環境（mediagent-e2e）：建立測試資料、讓排程到期。
 * 平台一律是 MockAdapter，不會連到真實平台。
 */
import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const root = resolve(here, '..')

export const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:18100'
export const CRON_SECRET = process.env.E2E_CRON_SECRET ?? 'e2e-cron-secret'
/** seeds/seed_dev.py 的開發用密碼（只用於本機與 CI 的測試環境） */
export const SEED_PASSWORD = process.env.E2E_SEED_PASSWORD ?? 'mediagent-dev'

export const USERS = {
  admin: 'admin@club.test',
  publisher: 'publisher@club.test',
  writer: 'writer@club.test',
} as const

const COMPOSE = [
  'compose',
  '-p',
  process.env.E2E_COMPOSE_PROJECT ?? 'mediagent-e2e',
  '-f',
  resolve(root, '../docker-compose.yml'),
  '-f',
  resolve(root, 'docker-compose.e2e.yml'),
]

function compose(args: string[], input?: string): string {
  return execFileSync('docker', [...COMPOSE, ...args], { input, encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] })
}

/** 每次執行的唯一字尾：重跑測試時名稱不會撞到上一次建立的資料 */
export const RUN_ID = Date.now().toString(36)

export function seedUsers(): void {
  compose(['exec', '-T', 'api', 'python', '-m', 'seeds.seed_dev'])
}

export interface SeededAccount {
  id: number
  platform: 'threads' | 'instagram' | 'discord'
  name: string
}

/** 直接在資料庫建立平台帳號（模擬已完成平台授權） */
export function seedAccounts(specs: { platform: SeededAccount['platform']; name: string }[]): SeededAccount[] {
  const script = readFileSync(resolve(here, 'seed_accounts.py'), 'utf8')
  const output = compose(['exec', '-T', '-e', `E2E_ACCOUNTS=${JSON.stringify(specs)}`, 'api', 'python', '-'], script)
  return JSON.parse(output.trim().split('\n').at(-1) ?? '[]') as SeededAccount[]
}

/** 執行 SQL（只讀取或調整測試資料用） */
export function sql(statement: string): string {
  return compose(['exec', '-T', 'db', 'psql', '-U', 'mediagent', '-d', 'mediagent', '-tAc', statement]).trim()
}

/** 讓貼文的排程時間變成過去，再像外部定時任務一樣呼叫 /internal/publish-due */
export async function publishDuePost(postId: number): Promise<void> {
  sql(`UPDATE post SET scheduled_at = now() - interval '1 minute' WHERE id = ${Number(postId)}`)
  const response = await fetch(`${BASE_URL}/api/v1/internal/publish-due`, {
    method: 'POST',
    headers: { 'X-Cron-Secret': CRON_SECRET },
  })
  if (!response.ok) throw new Error(`publish-due 失敗：${response.status} ${await response.text()}`)
}

/** 以 API 登入取得 Access Token（給測試裡「另一個人」的操作用，例如管理員移除平台帳號） */
export async function apiToken(email: string): Promise<string> {
  const response = await fetch(`${BASE_URL}/api/v1/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password: SEED_PASSWORD }),
  })
  if (!response.ok) throw new Error(`登入失敗：${response.status}`)
  return ((await response.json()) as { access_token: string }).access_token
}
