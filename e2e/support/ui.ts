/** 畫面操作的共用步驟：都透過使用者看得到的文字與角色找元素，不依賴內部的 class。 */
import { expect, type Locator, type Page } from '@playwright/test'

import { SEED_PASSWORD } from './stack'

export async function login(page: Page, email: string, password = SEED_PASSWORD): Promise<void> {
  await page.goto('/login')
  await page.getByPlaceholder('name@club.org').fill(email)
  await page.getByLabel('密碼').fill(password)
  await page.getByRole('button', { name: '登入', exact: true }).click()
  await expect(page).not.toHaveURL(/\/login/)
}

export async function logout(page: Page): Promise<void> {
  await page.getByRole('button', { name: '登出', exact: true }).click()
  await expect(page).toHaveURL(/\/login/)
}

/** Element Plus 的確認對話框（ElMessageBox）：按下指定的按鈕 */
export async function confirmBox(page: Page, buttonName: string): Promise<void> {
  const box = page.getByRole('dialog').filter({ has: page.getByRole('button', { name: buttonName, exact: true }) })
  await box.getByRole('button', { name: buttonName, exact: true }).click()
}

/** 畫面上方的提示訊息（ElMessage） */
export function toast(page: Page, text: string | RegExp): Locator {
  return page.locator('.el-message').filter({ hasText: text })
}

/** 發佈結果表格中某個平台帳號的那一列 */
export function resultRow(page: Page, accountName: string): Locator {
  return page.locator('.el-card').filter({ hasText: '發佈' }).locator('tr').filter({ hasText: accountName })
}

/** 幹部帳號列表：在某個帳號那一列的角色下拉選單選擇角色 */
export async function chooseRole(page: Page, email: string, role: string): Promise<void> {
  const row = page.getByRole('row').filter({ hasText: email })
  // Element Plus 下拉選單的 combobox 本身幾乎沒有大小，點外框才會打開
  await row.locator('.el-select__wrapper').click()
  await page.getByRole('option', { name: role, exact: true }).click()
}

/** 從網址取出貼文 ID */
export function postIdFromUrl(page: Page): number {
  const match = /\/posts\/(\d+)/.exec(page.url())
  if (!match) throw new Error(`網址不是貼文頁：${page.url()}`)
  return Number(match[1])
}
