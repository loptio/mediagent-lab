<script setup lang="ts">
/** 稽核查詢（FR-19，管理員）：一般稽核、登入失敗、平台帳號連結失敗依時間由新到舊。篩選與分頁放在網址上。 */
import { keepPreviousData, useQuery } from '@tanstack/vue-query'
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { auditApi, platformAccountsApi, usersApi, type AuditQuery } from '@/shared/api/endpoints'
import { AUDIT_FILTER_ACTIONS, AUDIT_KIND_LABELS, label, PLATFORM_LABELS } from '@/shared/labels'
import QueryError from '@/shared/QueryError.vue'
import { addDays, formatTaipei, taipeiToUtcIso } from '@/shared/time'

import { toRow } from './auditFormat'

const PAGE_SIZES = [20, 50, 100]
const KIND_TAGS = { audit: 'info', login_security: 'danger', platform_auth: 'warning' } as const

const route = useRoute()
const router = useRouter()

function queryString(key: string): string {
  const value = route.query[key]
  return typeof value === 'string' ? value : ''
}

// 操作者：使用者 ID，或 system（系統）
const actor = computed(() => queryString('actor'))
const account = computed(() => queryString('account'))
const action = computed(() => queryString('action'))
const dateRange = computed<[string, string] | null>(() => {
  const from = queryString('from')
  const to = queryString('to')
  return from && to ? [from, to] : null
})
const page = computed(() => Math.max(1, Number(route.query.page) || 1))
const pageSize = computed(() => {
  const size = Number(route.query.page_size)
  return PAGE_SIZES.includes(size) ? size : 20
})

function setQuery(next: Record<string, string | number | null | undefined>) {
  const merged: Record<string, string> = {}
  const current = { ...route.query, page: String(page.value), ...next } as Record<string, unknown>
  for (const [key, value] of Object.entries(current)) {
    if (value === null || value === undefined || value === '') continue
    if (key === 'page' && Number(value) === 1) continue
    if (key === 'page_size' && Number(value) === 20) continue
    merged[key] = String(value)
  }
  void router.replace({ query: merged })
}

function setDateRange(value: [string, string] | null) {
  setQuery({ from: value?.[0] ?? null, to: value?.[1] ?? null, page: 1 })
}

const apiQuery = computed<AuditQuery>(() => {
  const query: AuditQuery = { page: page.value, page_size: pageSize.value }
  if (actor.value === 'system') query.actor_type = 'system'
  else if (actor.value) query.actor_id = Number(actor.value)
  if (account.value) query.account_id = Number(account.value)
  if (action.value) query.action = action.value
  // 日期以台灣時間的整天計算：含開始日 00:00，不含結束日隔天 00:00
  if (dateRange.value) {
    query.from = taipeiToUtcIso(dateRange.value[0], '00:00')
    query.to = taipeiToUtcIso(addDays(dateRange.value[1], 1), '00:00')
  }
  return query
})

const eventsQuery = useQuery({
  queryKey: ['audit-events', apiQuery],
  queryFn: () => auditApi.search(apiQuery.value),
  placeholderData: keepPreviousData,
})
const usersQuery = useQuery({ queryKey: ['users'], queryFn: usersApi.list })
const accountsQuery = useQuery({ queryKey: ['platform-accounts'], queryFn: platformAccountsApi.list })

const users = computed(() => usersQuery.data.value?.items ?? [])
const rows = computed(() => {
  const userNames = new Map(users.value.map((u) => [u.id, u.name]))
  const accountNames = new Map(
    (accountsQuery.data.value?.items ?? []).map((a) => [a.id, `${label(PLATFORM_LABELS, a.platform)}・${a.account_name}`]),
  )
  const lookup = { user: (id: number) => userNames.get(id), platformAccount: (id: number) => accountNames.get(id) }
  return (eventsQuery.data.value?.items ?? []).map((event) => toRow(event, lookup))
})

const actionOptions = Object.entries(AUDIT_FILTER_ACTIONS).map(([value, text]) => ({ value, text }))
const hasFilter = computed(() => !!(actor.value || account.value || action.value || dateRange.value))
</script>

<template>
  <div class="page">
    <div class="page-header">
      <h1>稽核紀錄</h1>
    </div>

    <div class="filters">
      <el-select
        :model-value="actor"
        placeholder="操作者"
        clearable
        filterable
        style="width: 160px"
        @update:model-value="(value: string) => setQuery({ actor: value, page: 1 })"
      >
        <el-option label="系統" value="system" />
        <el-option v-for="user in users" :key="user.id" :label="user.name" :value="String(user.id)" />
      </el-select>
      <el-tooltip content="這個帳號的登入失敗，以及以這個帳號為對象的操作" placement="top">
        <el-select
          :model-value="account"
          placeholder="對應帳號"
          clearable
          filterable
          style="width: 160px"
          @update:model-value="(value: string) => setQuery({ account: value, page: 1 })"
        >
          <el-option v-for="user in users" :key="user.id" :label="user.name" :value="String(user.id)" />
        </el-select>
      </el-tooltip>
      <el-select
        :model-value="action"
        placeholder="操作類型"
        clearable
        filterable
        style="width: 180px"
        @update:model-value="(value: string) => setQuery({ action: value, page: 1 })"
      >
        <el-option v-for="option in actionOptions" :key="option.value" :label="option.text" :value="option.value" />
      </el-select>
      <el-date-picker
        :model-value="dateRange"
        type="daterange"
        value-format="YYYY-MM-DD"
        start-placeholder="開始日期"
        end-placeholder="結束日期"
        range-separator="至"
        style="width: 260px"
        @update:model-value="setDateRange"
      />
      <el-button v-if="hasFilter" text @click="router.replace({ query: {} })">清除篩選</el-button>
    </div>
    <p class="muted note">時間為台灣時間；依操作者篩選時不含登入失敗（登入失敗沒有操作者）。</p>

    <el-skeleton v-if="eventsQuery.isPending.value" :rows="6" animated />
    <QueryError v-else-if="eventsQuery.isError.value" :error="eventsQuery.error.value" @retry="eventsQuery.refetch()" />
    <template v-else-if="eventsQuery.data.value">
      <el-empty v-if="rows.length === 0" :description="hasFilter ? '沒有符合條件的紀錄' : '還沒有稽核紀錄'" />
      <el-table v-else v-loading="eventsQuery.isFetching.value" :data="rows" row-key="key">
        <el-table-column label="時間" width="150">
          <template #default="{ row }">{{ formatTaipei(row.occurredAt) }}</template>
        </el-table-column>
        <el-table-column label="類別" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="KIND_TAGS[row.kind as keyof typeof KIND_TAGS]" disable-transitions>
              {{ label(AUDIT_KIND_LABELS, row.kind) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="actor" label="操作者" width="110" />
        <el-table-column prop="action" label="操作" width="150" />
        <el-table-column label="對象" min-width="160">
          <template #default="{ row }">
            <RouterLink v-if="row.postId" :to="{ name: 'post-edit', params: { id: row.postId } }">{{ row.target }}</RouterLink>
            <span v-else>{{ row.target }}</span>
          </template>
        </el-table-column>
        <el-table-column label="詳情" min-width="240">
          <template #default="{ row }">
            <div v-for="(line, index) in row.details" :key="index" class="detail">{{ line }}</div>
            <span v-if="row.details.length === 0" class="muted">—</span>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination
        v-if="eventsQuery.data.value.total > 0"
        class="pagination"
        background
        layout="total, sizes, prev, pager, next"
        :total="eventsQuery.data.value.total"
        :current-page="eventsQuery.data.value.page"
        :page-size="eventsQuery.data.value.page_size"
        :page-sizes="PAGE_SIZES"
        @current-change="(value: number) => setQuery({ page: value })"
        @size-change="(value: number) => setQuery({ page_size: value, page: 1 })"
      />
    </template>
  </div>
</template>

<style scoped>
.filters {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
}

.note {
  margin: 8px 0 16px;
}

.detail {
  font-size: 13px;
  line-height: 1.6;
}

.pagination {
  margin-top: 16px;
  justify-content: flex-end;
}
</style>
