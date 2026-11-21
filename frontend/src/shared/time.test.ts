import { describe, expect, it } from 'vitest'

import { addDays, formatTaipei, isFuture, nextSlotTaipei, taipeiToUtcIso, todayTaipei, toTaipeiInput } from './time'

describe('台灣時間換算', () => {
  it('UTC 顯示成台灣時間', () => {
    expect(formatTaipei('2026-10-06T04:00:00Z')).toBe('2026-10-06 12:00')
    expect(formatTaipei('2026-10-06T16:30:00Z')).toBe('2026-10-07 00:30')
    expect(formatTaipei(null)).toBe('—')
  })

  it('台灣時間輸入轉成 UTC ISO 字串（秒數為 0）', () => {
    expect(taipeiToUtcIso('2026-10-06', '12:00')).toBe('2026-10-06T04:00:00Z')
    expect(taipeiToUtcIso('2026-10-07', '00:30')).toBe('2026-10-06T16:30:00Z')
  })

  it('來回換算一致', () => {
    expect(toTaipeiInput(taipeiToUtcIso('2026-12-31', '23:55'))).toEqual({ date: '2026-12-31', time: '23:55' })
  })

  it('今天以台灣日期為準', () => {
    expect(todayTaipei(new Date('2026-10-06T16:00:00Z'))).toBe('2026-10-07')
  })

  it('建議時間是 10 分鐘後的第一個 5 分鐘整', () => {
    expect(nextSlotTaipei(new Date('2026-10-06T04:01:30Z'))).toEqual({ date: '2026-10-06', time: '12:15' })
    expect(nextSlotTaipei(new Date('2026-10-06T04:00:00Z'))).toEqual({ date: '2026-10-06', time: '12:10' })
  })

  it('判斷是否晚於現在', () => {
    const now = new Date('2026-10-06T04:00:00Z')
    expect(isFuture('2026-10-06', '12:05', now)).toBe(true)
    expect(isFuture('2026-10-06', '12:00', now)).toBe(false)
  })

  it('日期加減天數（跨月、跨年）', () => {
    expect(addDays('2026-10-31', 1)).toBe('2026-11-01')
    expect(addDays('2026-12-31', 1)).toBe('2027-01-01')
    expect(addDays('2026-03-01', -1)).toBe('2026-02-28')
  })
})
