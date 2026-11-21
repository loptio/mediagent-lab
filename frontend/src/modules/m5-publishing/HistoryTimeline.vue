<script setup lang="ts">
/** 發佈紀錄的變更歷程（FR-17、NFR-12）：依時間由舊到新，誰在什麼時候因為什麼原因改了狀態。 */
import { useQuery } from '@tanstack/vue-query'
import { computed } from 'vue'

import { postsApi, type PublishRecord } from '@/shared/api/endpoints'
import { HISTORY_REASON_LABELS, label, PLATFORM_LABELS, RECORD_STATUS_LABELS } from '@/shared/labels'
import QueryError from '@/shared/QueryError.vue'
import { formatTaipei } from '@/shared/time'

const props = defineProps<{ postId: number; records: PublishRecord[] }>()

const query = useQuery({
  queryKey: computed(() => ['publish-history', props.postId]),
  queryFn: () => postsApi.history(props.postId),
})

const accountByRecord = computed(() => {
  const map = new Map<number, string>()
  for (const record of props.records) {
    const account = record.platform_account
    map.set(record.id, `${label(PLATFORM_LABELS, account.platform)}・${account.account_name}`)
  }
  return map
})

defineExpose({ refetch: () => query.refetch() })
</script>

<template>
  <el-skeleton v-if="query.isPending.value" :rows="3" animated />
  <QueryError v-else-if="query.isError.value" :error="query.error.value" @retry="query.refetch()" />
  <el-empty v-else-if="!query.data.value?.items.length" :image-size="60" description="還沒有變更紀錄" />
  <el-timeline v-else class="timeline">
    <el-timeline-item
      v-for="(item, index) in query.data.value.items"
      :key="index"
      :timestamp="formatTaipei(item.changed_at)"
      placement="top"
    >
      <div class="line">
        <strong>{{ accountByRecord.get(item.publish_record_id) ?? `紀錄 #${item.publish_record_id}` }}</strong>
        <span>
          {{ item.from_status ? label(RECORD_STATUS_LABELS, item.from_status) : '（新增）' }} →
          {{ label(RECORD_STATUS_LABELS, item.to_status) }}
        </span>
      </div>
      <div class="muted">
        {{ label(HISTORY_REASON_LABELS, item.reason) }}・{{ item.actor ? item.actor.name : '系統' }}
      </div>
    </el-timeline-item>
  </el-timeline>
</template>

<style scoped>
.timeline {
  padding-left: 4px;
  margin-top: 8px;
}

.line {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
</style>
