<script setup lang="ts">
import { keepPreviousData, useQuery } from '@tanstack/vue-query'
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { postsApi, type PostListItem } from '@/shared/api/endpoints'
import { label, PLATFORM_LABELS, POST_STATUS_LABELS } from '@/shared/labels'
import QueryError from '@/shared/QueryError.vue'
import StatusTag from '@/shared/StatusTag.vue'
import { formatTaipei } from '@/shared/time'

const PAGE_SIZES = [20, 50, 100]

const route = useRoute()
const router = useRouter()

// 篩選與分頁放在網址上，重新整理或分享連結時保持一樣的畫面
const status = computed(() => (typeof route.query.status === 'string' ? route.query.status : ''))
const page = computed(() => Math.max(1, Number(route.query.page) || 1))
const pageSize = computed(() => {
  const size = Number(route.query.page_size)
  return PAGE_SIZES.includes(size) ? size : 20
})

function setQuery(next: { status?: string; page?: number; page_size?: number }) {
  const merged = { status: status.value, page: page.value, page_size: pageSize.value, ...next }
  void router.replace({
    query: {
      ...(merged.status ? { status: merged.status } : {}),
      ...(merged.page > 1 ? { page: String(merged.page) } : {}),
      ...(merged.page_size !== 20 ? { page_size: String(merged.page_size) } : {}),
    },
  })
}

const { data, isPending, isError, error, refetch, isFetching } = useQuery({
  queryKey: ['posts', status, page, pageSize],
  queryFn: () =>
    postsApi.list({ status: status.value || undefined, page: page.value, page_size: pageSize.value }),
  placeholderData: keepPreviousData,
})

const statusOptions = Object.entries(POST_STATUS_LABELS).map(([value, text]) => ({ value, text }))

function excerpt(content: string) {
  const text = content.replace(/\s+/g, ' ').trim()
  return text.length > 60 ? `${text.slice(0, 60)}…` : text
}

function openPost(row: PostListItem) {
  void router.push({ name: 'post-edit', params: { id: row.id } })
}
</script>

<template>
  <div class="page">
    <div class="page-header">
      <h1>貼文</h1>
      <div class="toolbar">
        <el-select
          :model-value="status"
          placeholder="全部狀態"
          clearable
          style="width: 160px"
          @update:model-value="(value: string) => setQuery({ status: value ?? '', page: 1 })"
        >
          <el-option v-for="option in statusOptions" :key="option.value" :label="option.text" :value="option.value" />
        </el-select>
        <el-button type="primary" @click="router.push({ name: 'post-new' })">新增貼文</el-button>
      </div>
    </div>

    <el-skeleton v-if="isPending" :rows="6" animated />
    <QueryError v-else-if="isError" :error="error" @retry="refetch()" />
    <template v-else-if="data">
      <el-empty
        v-if="data.items.length === 0"
        :description="status ? '沒有符合這個狀態的貼文' : '還沒有貼文，按「新增貼文」寫第一篇吧'"
      />
      <el-table
        v-else
        v-loading="isFetching"
        :data="data.items"
        class="clickable-rows"
        row-key="id"
        @row-click="openPost"
      >
        <el-table-column prop="id" label="#" width="64" />
        <el-table-column label="內容" min-width="260">
          <template #default="{ row }">{{ excerpt(row.content) }}</template>
        </el-table-column>
        <el-table-column label="狀態" width="110">
          <template #default="{ row }"><StatusTag :status="row.status" /></template>
        </el-table-column>
        <el-table-column label="目標平台帳號" min-width="180">
          <template #default="{ row }">
            <span v-if="row.targets.length === 0" class="muted">尚未選擇</span>
            <el-tag v-for="target in row.targets" :key="target.id" size="small" effect="plain" class="target-tag">
              {{ label(PLATFORM_LABELS, target.platform) }}・{{ target.account_name }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="排程時間" width="150">
          <template #default="{ row }">{{ formatTaipei(row.scheduled_at) }}</template>
        </el-table-column>
        <el-table-column label="建立者" width="110">
          <template #default="{ row }">{{ row.creator.name }}</template>
        </el-table-column>
        <el-table-column label="建立時間" width="150">
          <template #default="{ row }">{{ formatTaipei(row.created_at) }}</template>
        </el-table-column>
      </el-table>
      <el-pagination
        v-if="data.total > 0"
        class="pagination"
        background
        layout="total, sizes, prev, pager, next"
        :total="data.total"
        :current-page="data.page"
        :page-size="data.page_size"
        :page-sizes="PAGE_SIZES"
        @current-change="(value: number) => setQuery({ page: value })"
        @size-change="(value: number) => setQuery({ page_size: value, page: 1 })"
      />
    </template>
  </div>
</template>

<style scoped>
.target-tag {
  margin: 2px 4px 2px 0;
}

.pagination {
  margin-top: 16px;
  justify-content: flex-end;
}
</style>
