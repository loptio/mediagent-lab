<script setup lang="ts">
import { computed } from 'vue'

import {
  POST_STATUS_LABELS,
  POST_STATUS_TAGS,
  RECORD_STATUS_LABELS,
  RECORD_STATUS_TAGS,
  type PostStatus,
  type RecordStatus,
} from './labels'

const props = defineProps<{ status: string | null | undefined; kind?: 'post' | 'record' }>()

const tag = computed(() => {
  const status = props.status ?? ''
  if (props.kind === 'record') {
    return {
      text: RECORD_STATUS_LABELS[status as RecordStatus] ?? '未知',
      type: RECORD_STATUS_TAGS[status as RecordStatus] ?? 'info',
    }
  }
  return {
    text: POST_STATUS_LABELS[status as PostStatus] ?? '未知',
    type: POST_STATUS_TAGS[status as PostStatus] ?? 'info',
  }
})
</script>

<template>
  <el-tag :type="tag.type" effect="light" disable-transitions>{{ tag.text }}</el-tag>
</template>
