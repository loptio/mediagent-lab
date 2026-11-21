<script setup lang="ts">
import { computed } from 'vue'

import { errorMessage } from './api/errors'

const props = defineProps<{ error: unknown }>()
const emit = defineEmits<{ retry: [] }>()
const message = computed(() => errorMessage(props.error))
</script>

<template>
  <el-result icon="error" title="載入失敗" :sub-title="message">
    <template #extra>
      <el-button type="primary" @click="emit('retry')">重新載入</el-button>
    </template>
  </el-result>
</template>
