<script setup lang="ts">
/** 圖片（FR-11）：一則貼文一張 JPEG；比例不符 Instagram 時後端自動裁出 Instagram 版本（BR-06）。 */
import { useMutation } from '@tanstack/vue-query'
import { ElMessage, ElMessageBox, type UploadRawFile, type UploadRequestOptions } from 'element-plus'
import { computed } from 'vue'

import { postsApi, type Post } from '@/shared/api/endpoints'
import { ERROR_MESSAGES } from '@/shared/api/errors'

const MAX_BYTES = 8_000_000

const props = defineProps<{ post?: Post; canEdit: boolean }>()
const emit = defineEmits<{ changed: [] }>()

const image = computed(() => props.post?.image ?? null)
const hasInstagramTarget = computed(() => !!props.post?.targets.some((t) => t.platform === 'instagram'))

function formatBytes(bytes: number) {
  return bytes >= 1_000_000 ? `${(bytes / 1_000_000).toFixed(1)} MB` : `${Math.round(bytes / 1000)} KB`
}

/** 先在瀏覽器擋掉明顯不行的檔案，省一次上傳；真正的檢查在後端 */
function beforeUpload(file: UploadRawFile) {
  if (file.type !== 'image/jpeg') {
    ElMessage.warning(ERROR_MESSAGES.IMAGE_FORMAT_INVALID)
    return false
  }
  if (file.size > MAX_BYTES) {
    ElMessage.warning(ERROR_MESSAGES.IMAGE_TOO_LARGE)
    return false
  }
  return true
}

const uploadMutation = useMutation({
  mutationFn: (file: File) => postsApi.attachImage(props.post!.id, file),
  onSuccess: (result) => {
    ElMessage.success(result.ig_cropped ? '已附加圖片；Instagram 會使用裁切後的版本' : '已附加圖片')
    emit('changed')
  },
})

// el-upload 的自訂上傳：錯誤已由全域的 mutation 錯誤處理顯示，這裡吞掉避免 el-upload 再顯示一次
async function upload(options: UploadRequestOptions) {
  try {
    await uploadMutation.mutateAsync(options.file)
  } catch {
    /* 已顯示錯誤訊息 */
  }
}

const removeMutation = useMutation({
  mutationFn: () => postsApi.removeImage(props.post!.id),
  onSuccess: () => {
    ElMessage.success('已移除圖片')
    emit('changed')
  },
})

async function remove() {
  try {
    await ElMessageBox.confirm('確定要移除這張圖片嗎？', '移除圖片', {
      confirmButtonText: '移除',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  removeMutation.mutate()
}
</script>

<template>
  <div class="image-section">
    <h3 class="section">圖片</h3>
    <p v-if="!post" class="muted">建立草稿後可以附加圖片（JPEG，最多 8,000,000 位元組）。</p>

    <template v-else-if="image">
      <div class="versions">
        <figure>
          <img :src="image.public_url" alt="原圖" />
          <figcaption>原圖・{{ image.width }}×{{ image.height }}・{{ formatBytes(image.size_bytes) }}</figcaption>
        </figure>
        <figure>
          <img :src="image.ig_public_url" alt="Instagram 版本" />
          <figcaption>Instagram 版本・{{ image.ig_width }}×{{ image.ig_height }}</figcaption>
        </figure>
      </div>
      <el-alert
        v-if="image.ig_cropped"
        type="warning"
        :closable="false"
        show-icon
        title="Instagram 會使用裁切後的版本"
        description="原圖比例超出 Instagram 的 4:5～1.91:1，已從中間裁切；其他平台使用原圖。"
        class="alert"
      />
      <el-button
        v-if="canEdit"
        size="small"
        :loading="removeMutation.isPending.value"
        :disabled="hasInstagramTarget"
        @click="remove"
      >
        移除圖片
      </el-button>
      <span v-if="canEdit && hasInstagramTarget" class="muted hint">目標包含 Instagram，必須保留圖片</span>
    </template>

    <template v-else>
      <el-upload
        v-if="canEdit"
        :show-file-list="false"
        accept="image/jpeg"
        :before-upload="beforeUpload"
        :http-request="upload"
        :disabled="uploadMutation.isPending.value"
      >
        <el-button :loading="uploadMutation.isPending.value">附加圖片</el-button>
      </el-upload>
      <p class="muted">
        JPEG，最多 8,000,000 位元組。發到 Instagram 必須附圖；比例超出 4:5～1.91:1 時會自動裁出 Instagram 版本。
      </p>
    </template>
  </div>
</template>

<style scoped>
.section {
  font-size: 15px;
  margin: 20px 0 8px;
}

.versions {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}

figure {
  margin: 0;
}

img {
  display: block;
  max-height: 200px;
  max-width: 100%;
  border-radius: 6px;
  border: 1px solid var(--el-border-color-light);
  background: var(--el-fill-color-light);
}

figcaption {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 4px;
}

.alert {
  margin: 12px 0;
}

.hint {
  margin-left: 8px;
}
</style>
