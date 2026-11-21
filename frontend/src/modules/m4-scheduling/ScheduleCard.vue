<script setup lang="ts">
import { useMutation } from '@tanstack/vue-query'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, ref, watch } from 'vue'

import { postsApi, type Post } from '@/shared/api/endpoints'
import { useAuthStore } from '@/shared/auth'
import { formatTaipei, isFuture, nextSlotTaipei, taipeiToUtcIso, todayTaipei, toTaipeiInput } from '@/shared/time'

const props = defineProps<{ post: Post; dirty: boolean }>()
const emit = defineEmits<{ changed: [] }>()

const auth = useAuthStore()

const isScheduled = computed(() => props.post.status === 'SCHEDULED')
const isOwner = computed(() => props.post.creator.id === auth.user?.id)
// 撰稿者只能修改自己已排程貼文的時間，不能為草稿設定排程（BR-18）
const canSet = computed(() => auth.hasRole('publisher') || (isOwner.value && isScheduled.value))
const canCancel = computed(() => isScheduled.value && (auth.hasRole('publisher') || isOwner.value))

const date = ref('')
const time = ref('')

function resetInputs() {
  const initial = props.post.scheduled_at ? toTaipeiInput(props.post.scheduled_at) : nextSlotTaipei()
  date.value = initial.date
  time.value = initial.time
}
watch(() => props.post.scheduled_at, resetInputs, { immediate: true })

/** 不能選今天（台灣時間）以前的日期 */
function disabledDate(value: Date) {
  const pad = (n: number) => String(n).padStart(2, '0')
  const picked = `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}`
  return picked < todayTaipei()
}

const setMutation = useMutation({
  mutationFn: () => postsApi.setSchedule(props.post.id, taipeiToUtcIso(date.value, time.value)),
  onSuccess: () => {
    ElMessage.success(isScheduled.value ? '已修改排程時間' : '已設定排程')
    emit('changed')
  },
})

const cancelMutation = useMutation({
  mutationFn: () => postsApi.cancelSchedule(props.post.id),
  onSuccess: () => {
    ElMessage.success('已取消排程，貼文改回草稿')
    emit('changed')
  },
})

function submit() {
  if (!date.value || !time.value) {
    ElMessage.warning('請選擇日期與時間')
    return
  }
  if (!isFuture(date.value, time.value)) {
    ElMessage.warning('排程時間必須晚於現在')
    return
  }
  setMutation.mutate()
}

async function cancel() {
  try {
    await ElMessageBox.confirm('取消後貼文會改回草稿，不會在排程時間發佈。確定要取消排程嗎？', '取消排程', {
      confirmButtonText: '取消排程',
      cancelButtonText: '保留排程',
      type: 'warning',
    })
  } catch {
    return
  }
  cancelMutation.mutate()
}
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div class="card-title">排程</div>
    </template>

    <p v-if="isScheduled" class="current">
      預計發佈時間：<strong>{{ formatTaipei(post.scheduled_at) }}</strong>（台灣時間）
    </p>
    <p v-else-if="canSet" class="muted">選擇台灣時間，時間到由系統自動發佈。只能選 5 分鐘整。</p>

    <template v-if="canSet">
      <div class="pickers">
        <el-date-picker
          v-model="date"
          type="date"
          value-format="YYYY-MM-DD"
          format="YYYY-MM-DD"
          placeholder="日期"
          :disabled-date="disabledDate"
          :clearable="false"
          style="width: 150px"
        />
        <el-time-select
          v-model="time"
          start="00:00"
          end="23:55"
          step="00:05"
          format="HH:mm"
          placeholder="時間"
          :clearable="false"
          style="width: 120px"
        />
        <el-button type="primary" :loading="setMutation.isPending.value" :disabled="dirty" @click="submit">
          {{ isScheduled ? '修改排程時間' : '設定排程' }}
        </el-button>
        <el-button
          v-if="canCancel"
          :loading="cancelMutation.isPending.value"
          :disabled="dirty"
          @click="cancel"
        >
          取消排程
        </el-button>
      </div>
    </template>
    <template v-else>
      <p class="muted">撰稿者不能為草稿設定排程，寫好後請通知發佈者或管理員。</p>
      <el-button v-if="canCancel" :loading="cancelMutation.isPending.value" @click="cancel">取消排程</el-button>
    </template>
    <p v-if="dirty" class="dirty-hint">內容或目標有尚未儲存的變更，請先儲存再設定排程。</p>
  </el-card>
</template>

<style scoped>
.card-title {
  font-weight: 600;
}

.current {
  margin-top: 0;
}

.pickers {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
}

.dirty-hint {
  color: var(--el-color-warning);
  font-size: 13px;
  margin-bottom: 0;
}
</style>
