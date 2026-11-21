<script setup lang="ts">
import { Check } from '@element-plus/icons-vue'

import type { PlatformAccount } from '@/shared/api/endpoints'
import { PLATFORM_LABELS, type Platform } from '@/shared/labels'

const props = defineProps<{ accounts: PlatformAccount[]; disabled?: boolean }>()
const selected = defineModel<number[]>({ required: true })

function isSelected(id: number) {
  return selected.value.includes(id)
}

/** 授權失效的帳號不能新增為目標（BR-08），但已選的可以取消 */
function isBlocked(account: PlatformAccount) {
  return account.auth_status !== 'valid' && !isSelected(account.id)
}

function toggle(account: PlatformAccount) {
  if (props.disabled || isBlocked(account)) return
  selected.value = isSelected(account.id)
    ? selected.value.filter((id) => id !== account.id)
    : [...selected.value, account.id]
}

const PLATFORM_COLORS: Record<Platform, string> = {
  discord: '#5865f2',
  threads: '#101010',
  instagram: '#d62976',
}
</script>

<template>
  <div class="targets">
    <button
      v-for="account in accounts"
      :key="account.id"
      type="button"
      class="target"
      :class="{ selected: isSelected(account.id), blocked: isBlocked(account), disabled }"
      :disabled="disabled || isBlocked(account)"
      :aria-pressed="isSelected(account.id)"
      @click="toggle(account)"
    >
      <span class="badge" :style="{ background: PLATFORM_COLORS[account.platform as Platform] }">
        {{ PLATFORM_LABELS[account.platform as Platform]?.[0] ?? '?' }}
      </span>
      <span class="text">
        <span class="name">{{ account.account_name }}</span>
        <span class="platform">
          {{ PLATFORM_LABELS[account.platform as Platform] ?? '未知平台' }}
          <template v-if="account.auth_status !== 'valid'">・<span class="invalid">授權失效，需重新連結</span></template>
        </span>
      </span>
      <el-icon v-if="isSelected(account.id)" class="check"><Check /></el-icon>
    </button>
  </div>
</template>

<style scoped>
.targets {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 8px;
}

.target {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
  background: var(--el-bg-color);
  cursor: pointer;
  text-align: left;
  font: inherit;
  color: inherit;
  filter: grayscale(1);
  opacity: 0.75;
  transition:
    border-color 0.15s,
    opacity 0.15s;
}

.target.selected {
  border-color: var(--el-color-primary);
  box-shadow: 0 0 0 1px var(--el-color-primary) inset;
  filter: none;
  opacity: 1;
}

.target:hover:not(:disabled) {
  opacity: 1;
}

.target:disabled {
  cursor: not-allowed;
}

.target.blocked {
  opacity: 0.45;
}

.badge {
  flex: none;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  color: #fff;
  display: grid;
  place-items: center;
  font-weight: 700;
}

.text {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
}

.name {
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.platform {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.invalid {
  color: var(--el-color-danger);
}

.check {
  color: var(--el-color-primary);
}
</style>
