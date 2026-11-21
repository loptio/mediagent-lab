<script setup lang="ts">
import { computed } from 'vue'

import { PLATFORM_LABELS, type Platform } from '@/shared/labels'

import { charUsage } from './charCount'

const props = defineProps<{ content: string; platforms: Platform[] }>()

const usages = computed(() => props.platforms.map((platform) => charUsage(platform, props.content)))

function percent(count: number, limit: number) {
  return Math.min(100, Math.round((count / limit) * 100))
}

function status(count: number, limit: number) {
  if (count > limit) return 'exception'
  if (count > limit * 0.9) return 'warning'
  return undefined
}
</script>

<template>
  <div class="counters">
    <div v-for="usage in usages" :key="usage.platform" class="counter" :class="{ over: usage.over }">
      <div class="counter-head">
        <span>{{ PLATFORM_LABELS[usage.platform] }}</span>
        <span class="numbers">{{ usage.count }}／{{ usage.limit }}</span>
      </div>
      <el-progress
        :percentage="percent(usage.count, usage.limit)"
        :status="status(usage.count, usage.limit)"
        :show-text="false"
        :stroke-width="6"
      />
      <div v-if="usage.over" class="hint over-hint">超過 {{ usage.count - usage.limit }} 字，發佈會被拒絕</div>
      <div v-else-if="usage.platform === 'threads'" class="hint">emoji 依 UTF-8 位元組數計算（多數 emoji 算 4 字）</div>
    </div>
  </div>
</template>

<style scoped>
.counters {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 12px;
  margin-top: 8px;
}

.counter-head {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  margin-bottom: 4px;
}

.numbers {
  font-variant-numeric: tabular-nums;
}

.over .numbers {
  color: var(--el-color-danger);
  font-weight: 600;
}

.hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 2px;
}

.over-hint {
  color: var(--el-color-danger);
}
</style>
