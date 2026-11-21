/**
 * 情境一：管理員授權幹部（docs/requirements.md §3）
 * 管理員連結 Discord 與 Threads，建立幹部帳號，幹部可以登入；換屆時把新任幹部調整為管理員，再把自己調整為其他角色。
 */
import { expect, test } from '@playwright/test'

import { apiToken, BASE_URL, RUN_ID, USERS } from '../support/stack'
import { chooseRole, confirmBox, login, logout, toast } from '../support/ui'

const INITIAL_PASSWORD = 'e2e-initial-pass'

test('管理員連結平台帳號、建立幹部帳號，換屆調整角色', async ({ page }) => {
  const discordName = `社團公告-${RUN_ID}`
  const successor = { name: `新任社長-${RUN_ID}`, email: `successor-${RUN_ID}@club.test` }
  const outgoing = { name: `卸任社長-${RUN_ID}`, email: `outgoing-${RUN_ID}@club.test` }

  // 重跑時先移除上一次 mock 授權留下的 Threads 帳號（mock 平台固定回傳同一個帳號名稱）
  const adminToken = await apiToken(USERS.admin)
  const headers = { Authorization: `Bearer ${adminToken}` }
  const existing = (await (await fetch(`${BASE_URL}/api/v1/platform-accounts`, { headers })).json()) as {
    items: { id: number; account_name: string }[]
  }
  for (const account of existing.items.filter((a) => a.account_name === 'mock_threads')) {
    await fetch(`${BASE_URL}/api/v1/platform-accounts/${account.id}`, { method: 'DELETE', headers })
  }

  await test.step('管理員登入並連結 Discord（貼上 Webhook 網址，mock 模式不會連到 Discord）', async () => {
    await login(page, USERS.admin)
    await page.getByRole('menuitem', { name: '平台帳號' }).click()
    await page.getByRole('button', { name: '連結 Discord 頻道' }).click()
    const dialog = page.getByRole('dialog', { name: '連結 Discord 頻道' })
    await dialog.getByLabel('顯示名稱').fill(discordName)
    await dialog.getByLabel('Webhook 網址').fill('https://discord.com/api/webhooks/123456789012345678/e2e-mock-token')
    await dialog.getByRole('button', { name: '連結', exact: true }).click()
    await expect(toast(page, '已連結 Discord 頻道')).toBeVisible()
    await expect(page.getByRole('row').filter({ hasText: discordName })).toContainText('有效')
  })

  await test.step('連結 Threads：走平台授權流程（攔截授權頁，模擬使用者同意後導回）', async () => {
    await page.route('https://threads.test/**', async (route) => {
      const url = new URL(route.request().url())
      const state = encodeURIComponent(url.searchParams.get('state') ?? '')
      await route.fulfill({
        status: 302,
        headers: { location: `${url.searchParams.get('redirect_uri')}?code=e2e-code&state=${state}` },
      })
    })
    await page.getByRole('button', { name: '連結 Threads 帳號' }).click()
    // 整頁離開再回來，前端用 Refresh Token Cookie 恢復登入，直接顯示結果
    await expect(toast(page, '已連結平台帳號')).toBeVisible()
    const row = page.getByRole('row').filter({ hasText: 'mock_threads' })
    await expect(row).toContainText('Threads')
    await expect(row).toContainText('有效')
  })

  await test.step('建立兩位幹部帳號', async () => {
    await page.getByRole('menuitem', { name: '幹部帳號' }).click()
    for (const [officer, role] of [
      [successor, '發佈者'],
      [outgoing, '管理員'],
    ] as const) {
      await page.getByRole('button', { name: '建立幹部帳號' }).click()
      const dialog = page.getByRole('dialog', { name: '建立幹部帳號' })
      await dialog.getByLabel('Email').fill(officer.email)
      await dialog.getByLabel('姓名').fill(officer.name)
      await dialog.getByText(role, { exact: true }).click()
      await dialog.getByLabel('初始密碼').fill(INITIAL_PASSWORD)
      await dialog.getByRole('button', { name: '建立', exact: true }).click()
      await expect(toast(page, `已建立「${officer.name}」的帳號`)).toBeVisible()
      await expect(page.getByRole('row').filter({ hasText: officer.email })).toContainText('啟用')
    }
  })

  await test.step('幹部可以用新帳號登入', async () => {
    await logout(page)
    await login(page, successor.email, INITIAL_PASSWORD)
    await expect(page.getByRole('menuitem', { name: '貼文' })).toBeVisible()
    await expect(page.getByRole('menuitem', { name: '幹部帳號' })).toHaveCount(0)
    await logout(page)
  })

  await test.step('換屆：卸任社長把新任社長調整為管理員，再把自己調整為發佈者', async () => {
    await login(page, outgoing.email, INITIAL_PASSWORD)
    await page.getByRole('menuitem', { name: '幹部帳號' }).click()

    await chooseRole(page, successor.email, '管理員')
    await confirmBox(page, '調整')
    await expect(toast(page, `已把「${successor.name}」調整為管理員`)).toBeVisible()

    await chooseRole(page, outgoing.email, '發佈者')
    await expect(page.getByRole('dialog')).toContainText('調整後你會立刻失去管理員權限')
    await confirmBox(page, '調整')
    await expect(toast(page, `已把「${outgoing.name}」調整為發佈者`)).toBeVisible()
    // 角色立即生效：離開幹部帳號頁，選單也不再有管理員功能
    await expect(page).toHaveURL(/\/posts/)
    await expect(page.getByRole('menuitem', { name: '幹部帳號' })).toHaveCount(0)
    await logout(page)
  })

  await test.step('新任社長登入後可以管理幹部帳號', async () => {
    await login(page, successor.email, INITIAL_PASSWORD)
    await page.getByRole('menuitem', { name: '幹部帳號' }).click()
    await expect(page.getByRole('row').filter({ hasText: outgoing.email })).toContainText('啟用')
  })
})
