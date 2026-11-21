/**
 * 例外情境：部分平台發佈失敗（docs/requirements.md §3）
 * - Instagram 暫時無法連線 → 部分失敗 → 重試只重送 Instagram，Threads 與 Discord 不會重複發文
 * - 失敗的平台帳號已被移除 → 無法重試 → 複製為新草稿，重新選擇目標後再發佈
 *
 * 名稱以 e2e-fail-once- 開頭的帳號，mock 平台第一次會回報「平台暫時無法連線」，之後成功
 * （app/core/platforms.py 的 MOCK_FAIL_ONCE_PREFIX，只存在於 mock 模式）。
 */
import { fileURLToPath } from 'node:url'

import { expect, type Page, test } from '@playwright/test'

import { apiToken, BASE_URL, RUN_ID, seedAccounts, USERS } from '../support/stack'
import { confirmBox, login, postIdFromUrl, resultRow, toast } from '../support/ui'

const POSTER = fileURLToPath(new URL('../fixtures/poster-9x16.jpg', import.meta.url))

/** 建立附圖貼文、選目標、立即發佈，等到發佈結束 */
async function publishNow(page: Page, content: string, targetNames: string[]): Promise<number> {
  await page.getByRole('button', { name: '新增貼文' }).click()
  await page.getByPlaceholder('輸入要同步發佈的內容').fill(content)
  await page.getByRole('button', { name: '建立草稿' }).click()
  await expect(page).toHaveURL(/\/posts\/\d+$/)
  await page.locator('.image-section input[type=file]').setInputFiles(POSTER)
  await expect(toast(page, '已附加圖片')).toBeVisible()
  for (const name of targetNames) await page.getByRole('button', { name: new RegExp(name) }).click()
  await page.getByRole('button', { name: '儲存', exact: true }).click()
  await expect(toast(page, '已儲存')).toBeVisible()
  await page.getByRole('button', { name: '立即發佈' }).click()
  await confirmBox(page, '立即發佈')
  await expect(toast(page, '已開始發佈')).toBeVisible()
  return postIdFromUrl(page)
}

const status = (page: Page) => page.locator('.page-header .el-tag')

test('Instagram 暫時無法連線 → 部分失敗 → 重試只重送 Instagram', async ({ page }) => {
  const [threads, instagram, discord] = seedAccounts([
    { platform: 'threads', name: `club_threads_${RUN_ID}` },
    { platform: 'instagram', name: `e2e-fail-once-ig-${RUN_ID}` },
    { platform: 'discord', name: `公告頻道_${RUN_ID}` },
  ])
  const firstPublished: Record<string, string> = {}

  await test.step('立即發佈：Threads 與 Discord 成功，Instagram 失敗，貼文為部分失敗', async () => {
    await login(page, USERS.publisher)
    await publishNow(page, `社團成果展 12/20 開放參觀（${RUN_ID}）`, [threads.name, instagram.name, discord.name])
    await expect(status(page)).toHaveText('部分失敗', { timeout: 45_000 })
    await expect(resultRow(page, instagram.name)).toContainText('失敗')
    await expect(resultRow(page, instagram.name)).toContainText('平台暫時無法連線')
    for (const account of [threads, discord]) {
      const row = resultRow(page, account.name)
      await expect(row).toContainText('成功')
      firstPublished[account.name] = await row.locator('td').nth(2).innerText()
    }
  })

  await test.step('重試：只列出 Instagram，Threads 與 Discord 先前已成功不會重送', async () => {
    await page.getByRole('button', { name: '重試失敗的平台' }).click()
    const dialog = page.getByRole('dialog', { name: '重試發佈' })
    await expect(dialog.locator('ul').first()).toContainText(instagram.name)
    await expect(dialog).toContainText(`${threads.name}：先前已成功，不會重送`)
    await expect(dialog).toContainText(`${discord.name}：先前已成功，不會重送`)
    await dialog.getByRole('button', { name: '重試 1 個平台帳號' }).click()
    await expect(toast(page, '已開始重試')).toBeVisible()
  })

  await test.step('重試完成：Instagram 成功；Threads 與 Discord 的發佈時間不變，沒有重複發文', async () => {
    await expect(status(page)).toHaveText('發佈完成', { timeout: 45_000 })
    await expect(resultRow(page, instagram.name)).toContainText('成功')
    for (const account of [threads, discord]) {
      await expect(resultRow(page, account.name).locator('td').nth(2)).toHaveText(firstPublished[account.name])
    }
    // 變更歷程：只有 Instagram 有「重試發佈」，Threads 與 Discord 各只有一次「發佈貼文：成功」
    await page.getByText('變更歷程', { exact: true }).click()
    const history = page.locator('.el-timeline')
    await expect(history.locator('.el-timeline-item').filter({ hasText: '重試發佈：成功' })).toHaveCount(1)
    await expect(history.locator('.el-timeline-item').filter({ hasText: '重試發佈：成功' })).toContainText(instagram.name)
    for (const account of [threads, discord]) {
      const entries = history.locator('.el-timeline-item').filter({ hasText: account.name })
      await expect(entries.filter({ hasText: '發佈貼文：成功' })).toHaveCount(1)
      await expect(entries.filter({ hasText: '重試' })).toHaveCount(0)
    }
  })
})

test('失敗的平台帳號已移除 → 無法重試 → 複製為新草稿後重新發佈', async ({ page }) => {
  const [instagram, discord] = seedAccounts([
    { platform: 'instagram', name: `e2e-fail-once-old-ig-${RUN_ID}` },
    { platform: 'discord', name: `活動頻道_${RUN_ID}` },
  ])

  await login(page, USERS.publisher)
  await publishNow(page, `期末聚餐報名開始（${RUN_ID}）`, [instagram.name, discord.name])
  await expect(status(page)).toHaveText('部分失敗', { timeout: 45_000 })

  await test.step('管理員移除失敗的 Instagram 帳號', async () => {
    const token = await apiToken(USERS.admin)
    const response = await fetch(`${BASE_URL}/api/v1/platform-accounts/${instagram.id}`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
    })
    expect(response.status).toBe(204)
  })

  await test.step('重試時沒有可以重送的平台帳號，提示改用複製為新草稿', async () => {
    await page.reload()
    await expect(resultRow(page, instagram.name)).toContainText('已移除')
    await page.getByRole('button', { name: '重試失敗的平台' }).click()
    const dialog = page.getByRole('dialog', { name: '重試發佈' })
    await expect(dialog).toContainText('沒有可以重試的平台帳號')
    await expect(dialog).toContainText(`${instagram.name}：帳號已移除，請改用「複製為新草稿」`)
    await expect(dialog.getByRole('button', { name: '重試 0 個平台帳號' })).toBeDisabled()
    await dialog.getByRole('button', { name: '先不要' }).click()
  })

  await test.step('複製為新草稿：保留內容與圖片，重新選擇目標後發佈成功', async () => {
    const originalId = postIdFromUrl(page)
    await page.getByRole('button', { name: '複製為新草稿' }).click()
    await expect(toast(page, '請重新選擇目標平台帳號')).toBeVisible()
    await expect(page).not.toHaveURL(new RegExp(`/posts/${originalId}$`))
    await expect(page.getByPlaceholder('輸入要同步發佈的內容')).toHaveValue(`期末聚餐報名開始（${RUN_ID}）`)
    await expect(page.getByText('原圖・540×960')).toBeVisible()
    // 已移除的帳號不會出現在可選的目標中
    await expect(page.getByRole('button', { name: new RegExp(instagram.name) })).toHaveCount(0)

    await page.getByRole('button', { name: new RegExp(discord.name) }).click()
    await page.getByRole('button', { name: '儲存', exact: true }).click()
    await expect(toast(page, '已儲存')).toBeVisible()
    await page.getByRole('button', { name: '立即發佈' }).click()
    await confirmBox(page, '立即發佈')
    await expect(status(page)).toHaveText('發佈完成', { timeout: 45_000 })
    await expect(resultRow(page, discord.name)).toContainText('成功')
  })
})
