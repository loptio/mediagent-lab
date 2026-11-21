/**
 * 時間：API 一律 UTC（ISO 8601），畫面一律台灣時間（NFR-09）。
 * 台灣沒有日光節約時間，固定 UTC+8，換算不依賴使用者電腦的時區設定。
 */

const TAIPEI_OFFSET_MS = 8 * 60 * 60 * 1000
export const SCHEDULE_STEP_MINUTES = 5

const pad = (n: number) => String(n).padStart(2, '0')

/** 台灣時間的年月日時分（用 UTC 欄位讀取已加 8 小時的時間） */
function taipeiParts(date: Date) {
  const shifted = new Date(date.getTime() + TAIPEI_OFFSET_MS)
  return {
    date: `${shifted.getUTCFullYear()}-${pad(shifted.getUTCMonth() + 1)}-${pad(shifted.getUTCDate())}`,
    time: `${pad(shifted.getUTCHours())}:${pad(shifted.getUTCMinutes())}`,
  }
}

/** 顯示格式 `2026-10-06 12:00`（台灣時間） */
export function formatTaipei(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  const parts = taipeiParts(date)
  return `${parts.date} ${parts.time}`
}

/** UTC ISO 字串 → 排程表單用的台灣日期與時間 */
export function toTaipeiInput(iso: string): { date: string; time: string } {
  return taipeiParts(new Date(iso))
}

/** 台灣日期 `YYYY-MM-DD` + 時間 `HH:mm` → API 用的 UTC ISO 字串（秒數為 0） */
export function taipeiToUtcIso(date: string, time: string): string {
  const [y, m, d] = date.split('-').map(Number)
  const [hh, mm] = time.split(':').map(Number)
  const utcMs = Date.UTC(y, m - 1, d, hh, mm) - TAIPEI_OFFSET_MS
  return new Date(utcMs).toISOString().replace('.000Z', 'Z')
}

/** 今天（台灣）的日期 `YYYY-MM-DD` */
export function todayTaipei(now: Date = new Date()): string {
  return taipeiParts(now).date
}

/** 建議的排程時間：現在起至少 leadMinutes 分鐘後的第一個 5 分鐘整（台灣時間） */
export function nextSlotTaipei(now: Date = new Date(), leadMinutes = 10): { date: string; time: string } {
  const stepMs = SCHEDULE_STEP_MINUTES * 60 * 1000
  const slot = Math.ceil((now.getTime() + leadMinutes * 60 * 1000) / stepMs) * stepMs
  return taipeiParts(new Date(slot))
}

/** 排程時間是否晚於現在 */
export function isFuture(date: string, time: string, now: Date = new Date()): boolean {
  return new Date(taipeiToUtcIso(date, time)).getTime() > now.getTime()
}
