import { describe, expect, it } from 'vitest'

import { charUsage, countChars } from './charCount'

describe('countChars', () => {
  it('一般文字每個字元算 1（中文、英文都一樣）', () => {
    expect(countChars('threads', '社課 7pm')).toBe(6)
    expect(countChars('discord', '社課 7pm')).toBe(6)
  })

  it('Threads：emoji 依 UTF-8 位元組數計算', () => {
    expect(countChars('threads', '🎸')).toBe(4) // U+1F3B8
    expect(countChars('threads', '☀')).toBe(3) // U+2600
    expect(countChars('threads', '社課🎸')).toBe(6)
  })

  it('Threads：組合 emoji 的連接符號與變體選擇符號也算位元組', () => {
    // 👍🏽 = U+1F44D + U+1F3FD
    expect(countChars('threads', '👍🏽')).toBe(8)
    // ❤️ = U+2764 + U+FE0F
    expect(countChars('threads', '❤️')).toBe(6)
  })

  it('Discord、Instagram 以 code point 計算，emoji 算 1', () => {
    expect(countChars('discord', '🎸')).toBe(1)
    expect(countChars('instagram', '👍🏽')).toBe(2)
  })
})

describe('charUsage', () => {
  it('超過上限時標示 over', () => {
    expect(charUsage('threads', 'a'.repeat(500)).over).toBe(false)
    expect(charUsage('threads', 'a'.repeat(501)).over).toBe(true)
    // 125 個 emoji 在 Threads 剛好 500
    expect(charUsage('threads', '🎸'.repeat(125))).toMatchObject({ count: 500, over: false })
    expect(charUsage('threads', '🎸'.repeat(126)).over).toBe(true)
    expect(charUsage('discord', '🎸'.repeat(2000)).over).toBe(false)
  })
})
