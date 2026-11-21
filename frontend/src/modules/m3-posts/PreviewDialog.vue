<script setup lang="ts">
/** 預覽（FR-20、BR-46）：各目標平台實際會送出的文字、字數、圖片版本與提醒；只讀取，不呼叫平台。 */
import { useQuery } from '@tanstack/vue-query'
import { computed } from 'vue'

import { postsApi } from '@/shared/api/endpoints'
import { IMAGE_VARIANT_LABELS, label, PLATFORM_LABELS, PREVIEW_WARNING_LABELS } from '@/shared/labels'
import QueryError from '@/shared/QueryError.vue'

const props = defineProps<{ postId: number }>()
const visible = defineModel<boolean>({ required: true })

const query = useQuery({
  queryKey: computed(() => ['post-preview', props.postId]),
  queryFn: () => postsApi.preview(props.postId),
  enabled: visible,
  // 每次打開都重新讀取，反映剛儲存的內容與目標
  staleTime: 0,
  gcTime: 0,
})
</script>

<template>
  <el-dialog v-model="visible" title="預覽各平台" width="min(760px, 94vw)" destroy-on-close>
    <el-skeleton v-if="query.isPending.value" :rows="5" animated />
    <QueryError v-else-if="query.isError.value" :error="query.error.value" @retry="query.refetch()" />
    <div v-else class="items">
      <el-card v-for="item in query.data.value?.items ?? []" :key="item.platform_account.id" shadow="never">
        <template #header>
          <div class="head">
            <strong>{{ label(PLATFORM_LABELS, item.platform_account.platform) }}・{{ item.platform_account.account_name }}</strong>
            <span class="count" :class="{ over: item.char_count > item.char_limit }">
              {{ item.char_count }}／{{ item.char_limit }} 字
            </span>
          </div>
        </template>
        <div v-if="item.warnings.length" class="warnings">
          <el-tag v-for="warning in item.warnings" :key="warning" type="warning" size="small" effect="light">
            {{ label(PREVIEW_WARNING_LABELS, warning) }}
          </el-tag>
        </div>
        <div class="body">
          <p class="text">{{ item.text }}</p>
          <figure v-if="item.image">
            <img :src="item.image.url" :alt="label(IMAGE_VARIANT_LABELS, item.image.variant)" />
            <figcaption>
              {{ label(IMAGE_VARIANT_LABELS, item.image.variant) }}・{{ item.image.width }}×{{ item.image.height }}
            </figcaption>
          </figure>
        </div>
      </el-card>
    </div>
  </el-dialog>
</template>

<style scoped>
.items {
  display: grid;
  gap: 12px;
}

.head {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}

.count {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  font-variant-numeric: tabular-nums;
}

.count.over {
  color: var(--el-color-danger);
  font-weight: 600;
}

.warnings {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}

.body {
  display: flex;
  gap: 16px;
  align-items: flex-start;
  flex-wrap: wrap;
}

.text {
  flex: 1 1 260px;
  white-space: pre-wrap;
  word-break: break-word;
  margin: 0;
}

figure {
  margin: 0;
}

img {
  display: block;
  max-height: 180px;
  max-width: 220px;
  border-radius: 6px;
  border: 1px solid var(--el-border-color-light);
}

figcaption {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 4px;
}
</style>
