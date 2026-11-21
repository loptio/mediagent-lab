<script setup lang="ts">
import { Loading } from '@element-plus/icons-vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, h, ref, watch } from 'vue'

import { postsApi, type Post, type PublishRecords } from '@/shared/api/endpoints'
import { useAuthStore } from '@/shared/auth'
import { FAILURE_REASON_LABELS, label, PLATFORM_LABELS } from '@/shared/labels'
import QueryError from '@/shared/QueryError.vue'
import StatusTag from '@/shared/StatusTag.vue'
import { formatTaipei } from '@/shared/time'

import HistoryTimeline from './HistoryTimeline.vue'
import { planRetry } from './retryWarnings'

const POLL_MS = 3000

const props = defineProps<{ post: Post; dirty: boolean }>()
const emit = defineEmits<{ changed: [] }>()

const auth = useAuthStore()
const queryClient = useQueryClient()
const postId = computed(() => props.post.id)

function hasPending(data: PublishRecords | undefined) {
  return !!data?.items.some((record) => record.status === 'PENDING')
}

// 發佈中時每 3 秒輪詢一次，直到沒有「待發佈」的紀錄（團隊規範 §9）
const recordsQuery = useQuery({
  queryKey: ['publish-records', postId],
  queryFn: () => postsApi.publishRecords(postId.value),
  refetchInterval: (query) =>
    props.post.status === 'PUBLISHING' || (props.post.status !== 'SCHEDULED' && hasPending(query.state.data))
      ? POLL_MS
      : false,
})
const records = computed(() => recordsQuery.data.value?.items ?? [])
const polling = computed(() => props.post.status === 'PUBLISHING')

// 輪詢看到貼文狀態變了（例如發佈中 → 發佈完成），通知上層重新讀取貼文
watch(
  () => recordsQuery.data.value?.post_status,
  (status) => {
    if (status && status !== props.post.status) emit('changed')
  },
)

const canPublish = computed(() => auth.hasRole('publisher'))
const canPublishNow = computed(() => ['DRAFT', 'SCHEDULED'].includes(props.post.status))
const canRetry = computed(() => ['PARTIALLY_FAILED', 'FAILED'].includes(props.post.status))
const isAdmin = computed(() => auth.hasRole('admin'))
// 變更歷程展開時才讀取
const historyOpen = ref<string[]>([])
// 發佈結果更新時，變更歷程也跟著更新
watch(
  () => recordsQuery.dataUpdatedAt.value,
  () => void queryClient.invalidateQueries({ queryKey: ['publish-history', props.post.id] }),
)

const publishMutation = useMutation({
  mutationFn: (type: 'immediate' | 'retry') => postsApi.publish(postId.value, type),
  onSuccess: (_, type) => {
    ElMessage.success(type === 'retry' ? '已開始重試，結果會自動更新' : '已開始發佈，結果會自動更新')
    void queryClient.invalidateQueries({ queryKey: ['publish-records', postId] })
    emit('changed')
  },
})

async function publishNow() {
  const targets = props.post.targets
  try {
    await ElMessageBox.confirm(
      h('div', [
        h('p', `現在就把這則貼文發到 ${targets.length} 個平台帳號：`),
        h(
          'ul',
          targets.map((t) => h('li', `${label(PLATFORM_LABELS, t.platform)}・${t.account_name}`)),
        ),
        props.post.status === 'SCHEDULED' ? h('p', '原本的排程時間會失效。') : null,
      ]),
      '立即發佈',
      { confirmButtonText: '立即發佈', cancelButtonText: '先不要', type: 'warning' },
    )
  } catch {
    return
  }
  publishMutation.mutate('immediate')
}

// ---------- 重試：先列出會重送與不會重送的平台帳號，Discord 結果不確定時要求先確認 ----------
const retryDialog = ref(false)
const channelChecked = ref(false)
const invalidAccountIds = computed(
  () => new Set(props.post.targets.filter((t) => t.auth_status !== 'valid').map((t) => t.id)),
)
const retryPlan = computed(() => planRetry(records.value, invalidAccountIds.value))

function openRetry() {
  channelChecked.value = false
  retryDialog.value = true
}

function confirmRetry() {
  retryDialog.value = false
  publishMutation.mutate('retry')
}

function skipReason(record: (typeof records.value)[number]) {
  if (record.status === 'SUCCEEDED') return '先前已成功，不會重送'
  if (record.platform_account.removed) return '帳號已移除，請改用「複製為新草稿」'
  if (invalidAccountIds.value.has(record.platform_account.id)) return '授權失效，請管理員重新連結後再重試'
  return '不會重送'
}
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div class="card-header">
        <span class="card-title">發佈</span>
        <div v-if="canPublish" class="toolbar">
          <el-button
            v-if="canPublishNow"
            type="primary"
            :disabled="dirty || post.targets.length === 0"
            :loading="publishMutation.isPending.value"
            @click="publishNow"
          >
            立即發佈
          </el-button>
          <el-button
            v-if="canRetry"
            type="warning"
            :loading="publishMutation.isPending.value"
            :disabled="recordsQuery.isPending.value"
            @click="openRetry"
          >
            重試失敗的平台
          </el-button>
        </div>
      </div>
    </template>

    <p v-if="canPublish && canPublishNow && post.targets.length === 0" class="muted">請先選擇目標平台帳號並儲存。</p>
    <p v-else-if="canPublish && canPublishNow && dirty" class="dirty-hint">有尚未儲存的變更，請先儲存再發佈。</p>
    <p v-if="!canPublish" class="muted">撰稿者不能發佈或重試，請通知發佈者或管理員。</p>

    <div v-if="polling" class="polling">
      <el-icon class="is-loading"><Loading /></el-icon>
      發佈中，每 3 秒自動更新結果…
    </div>

    <el-skeleton v-if="recordsQuery.isPending.value" :rows="3" animated />
    <QueryError v-else-if="recordsQuery.isError.value" :error="recordsQuery.error.value" @retry="recordsQuery.refetch()" />
    <el-empty
      v-else-if="records.length === 0"
      :image-size="80"
      description="尚未發佈。立即發佈或排程時間到之後，這裡會顯示各平台的結果。"
    />
    <el-table v-else :data="records" row-key="id" size="small">
      <el-table-column label="平台帳號" min-width="180">
        <template #default="{ row }">
          {{ label(PLATFORM_LABELS, row.platform_account.platform) }}・{{ row.platform_account.account_name }}
          <el-tag v-if="row.platform_account.removed" size="small" type="info">已移除</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="結果" width="90">
        <template #default="{ row }"><StatusTag kind="record" :status="row.status" /></template>
      </el-table-column>
      <el-table-column label="發佈時間" width="150">
        <template #default="{ row }">{{ formatTaipei(row.published_at) }}</template>
      </el-table-column>
      <el-table-column label="失敗原因" min-width="150">
        <template #default="{ row }">
          <span v-if="row.failure_reason">{{ label(FAILURE_REASON_LABELS, row.failure_reason) }}</span>
          <span v-else class="muted">—</span>
          <div v-if="isAdmin && row.platform_error_message" class="platform-error">
            {{ row.platform_error_message }}
          </div>
        </template>
      </el-table-column>
      <el-table-column label="貼文連結" width="100">
        <template #default="{ row }">
          <el-link
            v-if="row.platform_post_url"
            :href="row.platform_post_url"
            target="_blank"
            rel="noopener noreferrer"
            type="primary"
          >
            查看
          </el-link>
          <span v-else class="muted">—</span>
        </template>
      </el-table-column>
    </el-table>

    <el-collapse v-if="records.length" v-model="historyOpen" class="history">
      <el-collapse-item title="變更歷程" name="history">
        <HistoryTimeline v-if="historyOpen.includes('history')" :post-id="post.id" :records="records" />
      </el-collapse-item>
    </el-collapse>

    <el-dialog v-model="retryDialog" title="重試發佈" width="min(520px, 92vw)">
      <el-alert
        v-if="retryPlan.retry.length === 0"
        type="info"
        :closable="false"
        show-icon
        title="沒有可以重試的平台帳號"
        description="已移除的平台帳號請改用「複製為新草稿」重新選擇目標；授權失效的請管理員重新連結後再重試。"
        class="nothing-to-retry"
      />
      <p v-else>只會重送下列失敗的平台帳號：</p>
      <ul v-if="retryPlan.retry.length" class="plan-list">
        <li v-for="record in retryPlan.retry" :key="record.id">
          {{ label(PLATFORM_LABELS, record.platform_account.platform) }}・{{ record.platform_account.account_name }}
          <span class="muted">（上次：{{ label(FAILURE_REASON_LABELS, record.failure_reason) }}）</span>
        </li>
      </ul>
      <template v-if="retryPlan.skipped.length">
        <p class="muted">不會重送：</p>
        <ul class="plan-list muted">
          <li v-for="record in retryPlan.skipped" :key="record.id">
            {{ label(PLATFORM_LABELS, record.platform_account.platform) }}・{{ record.platform_account.account_name }}：{{
              skipReason(record)
            }}
          </li>
        </ul>
      </template>
      <el-alert v-if="retryPlan.needsChannelCheck.length" type="warning" :closable="false" show-icon>
        <template #title>請先到 Discord 頻道確認訊息是否已發出</template>
        <p class="alert-body">
          {{ retryPlan.needsChannelCheck.map((r) => `「${r.platform_account.account_name}」`).join('、') }}
          上次的失敗原因是「發佈逾時」或「平台暫時無法連線」，訊息可能其實已經送出。重試會再發一次，可能造成重複貼文。
        </p>
        <el-checkbox v-model="channelChecked">我已到頻道確認，訊息沒有發出</el-checkbox>
      </el-alert>
      <template #footer>
        <el-button @click="retryDialog = false">先不要</el-button>
        <el-button
          type="warning"
          :disabled="retryPlan.retry.length === 0 || (retryPlan.needsChannelCheck.length > 0 && !channelChecked)"
          @click="confirmRetry"
        >
          重試 {{ retryPlan.retry.length }} 個平台帳號
        </el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<style scoped>
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.card-title {
  font-weight: 600;
}

.polling {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--el-color-warning);
  font-size: 13px;
  margin-bottom: 8px;
}

.dirty-hint {
  color: var(--el-color-warning);
  font-size: 13px;
}

.platform-error {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  word-break: break-all;
}

.history {
  margin-top: 12px;
}

.nothing-to-retry {
  margin-bottom: 12px;
}

.plan-list {
  margin: 4px 0 12px;
  padding-left: 20px;
}

.alert-body {
  margin: 4px 0 8px;
}
</style>
