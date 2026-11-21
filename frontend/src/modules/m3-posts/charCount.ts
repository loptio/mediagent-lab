/**
 * 各平台的字數計算與上限，與後端 Adapter 的 count_chars 相同：
 * - Threads 上限 500：emoji 以 UTF-8 位元組數計算，其餘每個字元算 1（app/m2_platforms/adapters/threads.py）
 * - Discord 上限 2000、Instagram 上限 2200：以 Unicode 字元（code point）計算
 * 前端只做提示，真正的檢查在後端。
 */

import type { Platform } from '@/shared/labels'

export const CHAR_LIMITS: Record<Platform, number> = {
  threads: 500,
  discord: 2000,
  instagram: 2200,
}

/** 與後端 _is_emoji 相同的範圍 */
export function isThreadsEmoji(codePoint: number): boolean {
  return (
    (codePoint >= 0x1f000 && codePoint <= 0x1faff) ||
    (codePoint >= 0x2600 && codePoint <= 0x27bf) ||
    (codePoint >= 0x2b00 && codePoint <= 0x2bff) ||
    codePoint === 0x200d ||
    codePoint === 0xfe0f
  )
}

function utf8Bytes(codePoint: number): number {
  if (codePoint < 0x80) return 1
  if (codePoint < 0x800) return 2
  if (codePoint < 0x10000) return 3
  return 4
}

export function countChars(platform: Platform, text: string): number {
  // Array.from 以 code point 切開字串，和 Python 逐字元走訪相同
  const codePoints = Array.from(text, (char) => char.codePointAt(0) ?? 0)
  if (platform === 'threads') {
    return codePoints.reduce((sum, cp) => sum + (isThreadsEmoji(cp) ? utf8Bytes(cp) : 1), 0)
  }
  return codePoints.length
}

export interface CharUsage {
  platform: Platform
  count: number
  limit: number
  over: boolean
}

export function charUsage(platform: Platform, text: string): CharUsage {
  const count = countChars(platform, text)
  const limit = CHAR_LIMITS[platform]
  return { platform, count, limit, over: count > limit }
}
