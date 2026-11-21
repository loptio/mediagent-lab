/**
 * 情境二：撰寫與發佈貼文（docs/requirements.md §3）
 * 發佈者寫貼文、附一張 9:16 海報，選 Threads、Instagram、Discord，在預覽確認 Instagram 的裁切，
 * 設定排程；時間到後三個平台都成功，發佈結果顯示三則貼文連結。
 */
import { fileURLToPath } from 'node:url'

import { expect, test } from '@playwright/test'

import { publishDuePost, RUN_ID, seedAccounts, USERS } from '../support/stack'
import { login, postIdFromUrl, resultRow, toast } from '../support/ui'

const POSTER = fileURLToPath(new URL('../fixtures/poster-9x16.jpg', import.meta.url))
const CONTENT = '本週三 19:00 社課在活動中心 201，主題是指彈入門，歡迎新生帶吉他來！'

test('撰寫貼文、附圖、預覽裁切、設定排程，時間到後看到三個平台的連結', async ({ page }) => {
  const [threads, instagram, discord] = seedAccounts([
    { platform: 'threads', name: `guitar_threads_${RUN_ID}` },
    { platform: 'instagram', name: `guitar_ig_${RUN_ID}` },
    { platform: 'discord', name: `社課公告_${RUN_ID}` },
  ])
  let postId = 0

  await test.step('發佈者寫貼文並建立草稿', async () => {
    await login(page, USERS.publisher)
    await page.getByRole('button', { name: '新增貼文' }).click()
    await page.getByPlaceholder('輸入要同步發佈的內容').fill(CONTENT)
    await page.getByRole('button', { name: '建立草稿' }).click()
    await expect(toast(page, '已建立草稿')).toBeVisible()
    await expect(page).toHaveURL(/\/posts\/\d+$/)
    postId = postIdFromUrl(page)
  })

  await test.step('附加 9:16 海報：Instagram 自動從中間裁成 4:5', async () => {
    await page.locator('.image-section input[type=file]').setInputFiles(POSTER)
    await expect(toast(page, '已附加圖片；Instagram 會使用裁切後的版本')).toBeVisible()
    await expect(page.getByText('原圖・540×960')).toBeVisible()
    await expect(page.getByText('Instagram 版本・540×675')).toBeVisible()
    await expect(page.getByText('Instagram 會使用裁切後的版本', { exact: true })).toBeVisible()
  })

  await test.step('選擇 Threads、Instagram、Discord 並儲存', async () => {
    for (const account of [threads, instagram, discord]) {
      await page.getByRole('button', { name: new RegExp(account.name) }).click()
    }
    await page.getByRole('button', { name: '儲存', exact: true }).click()
    await expect(toast(page, '已儲存')).toBeVisible()
  })

  await test.step('預覽：Instagram 用裁切後的版本，Threads 與 Discord 用原圖', async () => {
    await page.getByRole('button', { name: '預覽各平台' }).click()
    const preview = page.getByRole('dialog', { name: '預覽各平台' })
    const card = (name: string) => preview.locator('.el-card').filter({ hasText: name })
    await expect(card(instagram.name)).toContainText('Instagram 版本・540×675')
    await expect(card(instagram.name)).toContainText('Instagram 會使用裁切後的圖片')
    await expect(card(threads.name)).toContainText('原圖・540×960')
    await expect(card(discord.name)).toContainText('原圖・540×960')
    for (const name of [threads.name, instagram.name, discord.name]) {
      await expect(card(name)).toContainText(CONTENT)
    }
    await page.keyboard.press('Escape')
    await expect(preview).toBeHidden()
  })

  await test.step('設定排程（預設為 10 分鐘後的第一個 5 分鐘整，台灣時間）', async () => {
    await page.getByRole('button', { name: '設定排程' }).click()
    await expect(toast(page, '已設定排程')).toBeVisible()
    await expect(page.getByText('預計發佈時間')).toBeVisible()
    for (const name of [threads.name, instagram.name, discord.name]) {
      await expect(resultRow(page, name)).toContainText('待發佈')
    }
  })

  await test.step('排程時間到：三個平台都成功，顯示三則貼文連結', async () => {
    await publishDuePost(postId)
    await page.reload()
    await expect(page.locator('.page-header .el-tag')).toHaveText('發佈完成', { timeout: 45_000 })
    for (const [account, host] of [
      [threads, 'threads.test'],
      [instagram, 'instagram.test'],
      [discord, 'discord.test'],
    ] as const) {
      const row = resultRow(page, account.name)
      await expect(row).toContainText('成功')
      await expect(row.getByRole('link', { name: '查看' })).toHaveAttribute('href', new RegExp(`^https://${host}/p/`))
    }
  })
})
