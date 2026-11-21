<script setup lang="ts">
/**
 * 貼文編輯頁（《系統架構設計》§4.4）：M3 內容、M4 目標與排程、M5 發佈與結果。
 * 新貼文先建立草稿，之後的排程與發佈都針對已儲存的內容。
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRouter } from 'vue-router'

import { platformAccountsApi, postsApi } from '@/shared/api/endpoints'
import { useAuthStore } from '@/shared/auth'
import type { Platform } from '@/shared/labels'
import QueryError from '@/shared/QueryError.vue'
import StatusTag from '@/shared/StatusTag.vue'
import { formatTaipei } from '@/shared/time'
import ScheduleCard from '@/modules/m4-scheduling/ScheduleCard.vue'
import TargetPicker from '@/modules/m4-scheduling/TargetPicker.vue'
import PublishPanel from '@/modules/m5-publishing/PublishPanel.vue'

import CharCounter from './CharCounter.vue'
import { charUsage } from './charCount'
import ImageSection from './ImageSection.vue'
import PreviewDialog from './PreviewDialog.vue'

const props = defineProps<{ id?: number }>()

const auth = useAuthStore()
const router = useRouter()
const queryClient = useQueryClient()

const isNew = computed(() => props.id === undefined)
const postId = computed(() => props.id ?? 0)

const postQuery = useQuery({
  queryKey: ['post', postId],
  queryFn: () => postsApi.get(postId.value),
  enabled: computed(() => !isNew.value),
})
const accountsQuery = useQuery({ queryKey: ['platform-accounts'], queryFn: platformAccountsApi.list })

const post = computed(() => postQuery.data.value)
const accounts = computed(() => accountsQuery.data.value?.items ?? [])

// ---------- 表單狀態：伺服器資料載入後填入，儲存前比較是否有變更 ----------
const content = ref('')
const targetIds = ref<number[]>([])

function sameIds(a: number[], b: number[]) {
  return a.length === b.length && a.every((id) => b.includes(id))
}

// 伺服器資料更新時（例如附加圖片後重新讀取），只有表單沒有未儲存的變更才覆蓋，避免吃掉正在輸入的內容
watch(
  post,
  (value, old) => {
    if (!value) return
    const wasClean =
      !old || (content.value === old.content && sameIds(targetIds.value, old.targets.map((t) => t.id)))
    if (value.id !== old?.id || wasClean) {
      content.value = value.content
      targetIds.value = value.targets.map((t) => t.id)
    }
  },
  { immediate: true },
)

const savedTargetIds = computed(() => post.value?.targets.map((t) => t.id) ?? [])
const contentChanged = computed(() => content.value !== (post.value?.content ?? ''))
const targetsChanged = computed(() => !sameIds(targetIds.value, savedTargetIds.value))
const dirty = computed(() => contentChanged.value || targetsChanged.value)

const isOwner = computed(() => isNew.value || post.value?.creator.id === auth.user?.id)
const editableStatus = computed(() => isNew.value || ['DRAFT', 'SCHEDULED'].includes(post.value?.status ?? ''))
const canEdit = computed(() => editableStatus.value && (auth.hasRole('publisher') || isOwner.value))
// 複製為新草稿：任何狀態都可以；撰稿者只能複製自己的貼文（BR-18）
const canCopy = computed(() => !isNew.value && (auth.hasRole('publisher') || isOwner.value))
const previewOpen = ref(false)

// 字數提示：有選目標就看目標的平台，還沒選就先顯示 Threads 與 Discord
const counterPlatforms = computed<Platform[]>(() => {
  const selected = accounts.value.filter((a) => targetIds.value.includes(a.id)).map((a) => a.platform as Platform)
  const unique = [...new Set(selected)]
  return unique.length ? unique : ['threads', 'discord']
})
const overLimit = computed(() =>
  accounts.value
    .filter((a) => targetIds.value.includes(a.id))
    .some((a) => charUsage(a.platform as Platform, content.value).over),
)

function refresh() {
  void queryClient.invalidateQueries({ queryKey: ['post', postId] })
  void queryClient.invalidateQueries({ queryKey: ['posts'] })
  void queryClient.invalidateQueries({ queryKey: ['publish-records', postId] })
  void queryClient.invalidateQueries({ queryKey: ['publish-history'] })
}

// ---------- 儲存：新貼文先建立草稿再設定目標；既有貼文只送有變更的部分 ----------
const saveMutation = useMutation({
  mutationFn: async () => {
    if (isNew.value) {
      const created = await postsApi.create(content.value)
      try {
        if (targetIds.value.length) await postsApi.setTargets(created.id, targetIds.value)
      } finally {
        // 目標設定失敗也已經有草稿了，帶使用者到草稿頁繼續處理
        void router.replace({ name: 'post-edit', params: { id: created.id } })
      }
      return 'created'
    }
    if (contentChanged.value) await postsApi.update(postId.value, content.value)
    if (targetsChanged.value) await postsApi.setTargets(postId.value, targetIds.value)
    return 'updated'
  },
  onSuccess: (result) => {
    ElMessage.success(result === 'created' ? '已建立草稿' : '已儲存')
  },
  onSettled: () => {
    if (!isNew.value) refresh()
    void queryClient.invalidateQueries({ queryKey: ['posts'] })
  },
})

function save() {
  if (!content.value.trim()) {
    ElMessage.warning('貼文內容不可為空白')
    return
  }
  saveMutation.mutate()
}

function discard() {
  content.value = post.value?.content ?? ''
  targetIds.value = [...savedTargetIds.value]
}

const copyMutation = useMutation({
  mutationFn: () => postsApi.copy(postId.value),
  onSuccess: async (copy) => {
    ElMessage.success(`已複製為新草稿 #${copy.id}，請重新選擇目標平台帳號`)
    void queryClient.invalidateQueries({ queryKey: ['posts'] })
    await router.push({ name: 'post-edit', params: { id: copy.id } })
  },
})

let deleted = false
const deleteMutation = useMutation({
  mutationFn: () => postsApi.remove(postId.value),
  onSuccess: async () => {
    ElMessage.success('已刪除貼文')
    void queryClient.invalidateQueries({ queryKey: ['posts'] })
    deleted = true
    await router.push({ name: 'posts' })
  },
})

async function remove() {
  const scheduled = post.value?.status === 'SCHEDULED'
  try {
    await ElMessageBox.confirm(
      scheduled ? '這則貼文已排程，刪除後排程也會取消。確定要刪除嗎？' : '刪除後無法復原。確定要刪除這則貼文嗎？',
      '刪除貼文',
      { confirmButtonText: '刪除', cancelButtonText: '取消', type: 'warning', confirmButtonClass: 'el-button--danger' },
    )
  } catch {
    return
  }
  deleteMutation.mutate()
}

// 有未儲存的變更時離開頁面先確認
onBeforeRouteLeave(async () => {
  if (!dirty.value || deleted || saveMutation.isPending.value) return true
  if (isNew.value && !content.value && targetIds.value.length === 0) return true
  try {
    await ElMessageBox.confirm('有尚未儲存的變更，離開後會遺失。確定要離開嗎？', '尚未儲存', {
      confirmButtonText: '離開',
      cancelButtonText: '留下來',
      type: 'warning',
    })
    return true
  } catch {
    return false
  }
})
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div class="title">
        <el-button text @click="router.push({ name: 'posts' })">← 貼文列表</el-button>
        <h1>{{ isNew ? '新增貼文' : `貼文 #${id}` }}</h1>
        <StatusTag v-if="post" :status="post.status" />
      </div>
      <div v-if="post" class="header-side">
        <span class="muted">{{ post.creator.name }} 建立於 {{ formatTaipei(post.created_at) }}</span>
        <el-tooltip :disabled="!dirty && post.targets.length > 0" :content="dirty ? '請先儲存變更' : '請先選擇目標平台帳號並儲存'">
          <span>
            <el-button :disabled="dirty || post.targets.length === 0" @click="previewOpen = true">預覽各平台</el-button>
          </span>
        </el-tooltip>
        <el-button v-if="canCopy" :loading="copyMutation.isPending.value" @click="copyMutation.mutate()">
          複製為新草稿
        </el-button>
      </div>
    </div>
    <PreviewDialog v-if="post" v-model="previewOpen" :post-id="post.id" />

    <el-skeleton v-if="!isNew && postQuery.isPending.value" :rows="8" animated />
    <QueryError v-else-if="!isNew && postQuery.isError.value" :error="postQuery.error.value" @retry="postQuery.refetch()" />
    <div v-else class="layout">
      <el-card shadow="never">
        <template #header>
          <div class="card-title">內容與目標</div>
        </template>

        <el-alert
          v-if="!editableStatus"
          type="info"
          :closable="false"
          show-icon
          title="這則貼文已進入發佈流程，內容與目標不能再修改。"
          class="block"
        />
        <el-alert
          v-else-if="!canEdit"
          type="info"
          :closable="false"
          show-icon
          title="撰稿者只能修改自己建立的貼文。"
          class="block"
        />

        <el-input
          v-model="content"
          type="textarea"
          :autosize="{ minRows: 6, maxRows: 16 }"
          placeholder="輸入要同步發佈的內容"
          :disabled="!canEdit"
        />
        <CharCounter :content="content" :platforms="counterPlatforms" />

        <ImageSection :post="post" :can-edit="canEdit" @changed="refresh" />

        <h3 class="section">目標平台帳號</h3>
        <el-skeleton v-if="accountsQuery.isPending.value" :rows="2" animated />
        <QueryError
          v-else-if="accountsQuery.isError.value"
          :error="accountsQuery.error.value"
          @retry="accountsQuery.refetch()"
        />
        <el-empty v-else-if="accounts.length === 0" :image-size="60" description="尚未連結平台帳號，請管理員先到「平台帳號」連結">
          <el-button @click="router.push({ name: 'platform-accounts' })">前往平台帳號</el-button>
        </el-empty>
        <TargetPicker v-else v-model="targetIds" :accounts="accounts" :disabled="!canEdit" />

        <div v-if="canEdit" class="actions">
          <el-button v-if="!isNew && dirty" @click="discard">還原</el-button>
          <el-button
            type="primary"
            :loading="saveMutation.isPending.value"
            :disabled="!isNew && !dirty"
            @click="save"
          >
            {{ isNew ? '建立草稿' : '儲存' }}
          </el-button>
          <span v-if="overLimit" class="warn">有平台超過字數上限，排程或發佈時會被拒絕</span>
          <span class="spacer" />
          <el-button v-if="!isNew" type="danger" plain :loading="deleteMutation.isPending.value" @click="remove">
            刪除
          </el-button>
        </div>
      </el-card>

      <template v-if="post">
        <ScheduleCard v-if="['DRAFT', 'SCHEDULED'].includes(post.status)" :post="post" :dirty="dirty" @changed="refresh" />
        <PublishPanel :post="post" :dirty="dirty" @changed="refresh" />
      </template>
    </div>
  </div>
</template>

<style scoped>
.header-side {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.title {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.layout {
  display: grid;
  gap: 16px;
}

.card-title {
  font-weight: 600;
}

.block {
  margin-bottom: 12px;
}

.section {
  font-size: 15px;
  margin: 20px 0 8px;
}

.actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 16px;
  flex-wrap: wrap;
}

.spacer {
  flex: 1;
}

.warn {
  color: var(--el-color-danger);
  font-size: 13px;
}
</style>
