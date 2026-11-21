<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { reactive, ref } from 'vue'

import { usersApi, type UserCreate, type UserDetail } from '@/shared/api/endpoints'
import { useAuthStore } from '@/shared/auth'
import { label, ROLE_LABELS, USER_STATUS_LABELS, type Role } from '@/shared/labels'
import QueryError from '@/shared/QueryError.vue'
import { formatTaipei } from '@/shared/time'

const auth = useAuthStore()
const queryClient = useQueryClient()

const { data, isPending, isError, error, refetch } = useQuery({ queryKey: ['users'], queryFn: usersApi.list })

// ---------- 建立幹部帳號 ----------
const createDialog = ref(false)
const formRef = ref<FormInstance>()
const form = reactive<UserCreate>({ email: '', name: '', role: 'writer', initial_password: '' })
const rules: FormRules = {
  email: [
    { required: true, message: '請輸入 Email', trigger: 'blur' },
    { type: 'email', message: 'Email 格式不正確', trigger: 'blur' },
  ],
  name: [{ required: true, message: '請輸入姓名', trigger: 'blur' }],
  role: [{ required: true, message: '請選擇角色', trigger: 'change' }],
  initial_password: [
    { required: true, message: '請輸入初始密碼', trigger: 'blur' },
    { min: 8, message: '初始密碼至少要 8 個字元', trigger: 'blur' },
  ],
}

function openCreate() {
  Object.assign(form, { email: '', name: '', role: 'writer', initial_password: '' })
  createDialog.value = true
}

const createMutation = useMutation({
  mutationFn: () => usersApi.create({ ...form, email: form.email.trim(), name: form.name.trim() }),
  onSuccess: (user) => {
    ElMessage.success(`已建立「${user.name}」的帳號，請把初始密碼私下交給對方`)
    createDialog.value = false
    form.initial_password = ''
    void queryClient.invalidateQueries({ queryKey: ['users'] })
  },
})

async function submitCreate() {
  if (!(await formRef.value?.validate().catch(() => false))) return
  createMutation.mutate()
}

// ---------- 停用、啟用 ----------
const statusMutation = useMutation({
  mutationFn: (args: { user: UserDetail; status: 'active' | 'disabled' }) =>
    usersApi.setStatus(args.user.id, args.status),
  onSuccess: (user) => {
    ElMessage.success(user.status === 'disabled' ? `已停用「${user.name}」` : `已啟用「${user.name}」`)
    void queryClient.invalidateQueries({ queryKey: ['users'] })
  },
})

async function disable(user: UserDetail) {
  try {
    await ElMessageBox.confirm(
      `停用後「${user.name}」會立刻被登出，也無法再登入。確定要停用嗎？`,
      '停用帳號',
      { confirmButtonText: '停用', cancelButtonText: '取消', type: 'warning', confirmButtonClass: 'el-button--danger' },
    )
  } catch {
    return
  }
  statusMutation.mutate({ user, status: 'disabled' })
}

function enable(user: UserDetail) {
  statusMutation.mutate({ user, status: 'active' })
}

// ---------- 調整角色（FR-04）：立即生效；系統至少要留一位啟用中的管理員（BR-19） ----------
const roleMutation = useMutation({
  mutationFn: (args: { user: UserDetail; role: Role }) => usersApi.setRole(args.user.id, args.role),
  onSuccess: (user) => {
    ElMessage.success(`已把「${user.name}」調整為${label(ROLE_LABELS, user.role)}`)
  },
  // 失敗時也重新讀取，讓下拉選單回到實際的角色
  onSettled: () => void queryClient.invalidateQueries({ queryKey: ['users'] }),
})

async function changeRole(user: UserDetail, role: Role) {
  if (role === user.role) return
  try {
    await ElMessageBox.confirm(
      user.id === auth.user?.id && role !== 'admin'
        ? `確定要把自己調整為${label(ROLE_LABELS, role)}嗎？調整後你會立刻失去管理員權限。`
        : `確定要把「${user.name}」從${label(ROLE_LABELS, user.role)}調整為${label(ROLE_LABELS, role)}嗎？`,
      '調整角色',
      { confirmButtonText: '調整', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  roleMutation.mutate({ user, role })
}

// ---------- 解除鎖定（FR-26）：連續登入失敗被鎖定時，管理員可以提前解除 ----------
const unlockMutation = useMutation({
  mutationFn: (user: UserDetail) => usersApi.unlock(user.id),
  onSuccess: (user) => {
    ElMessage.success(`已解除「${user.name}」的鎖定`)
    void queryClient.invalidateQueries({ queryKey: ['users'] })
  },
})
</script>

<template>
  <div class="page">
    <div class="page-header">
      <h1>幹部帳號</h1>
      <el-button type="primary" @click="openCreate">建立幹部帳號</el-button>
    </div>

    <el-skeleton v-if="isPending" :rows="5" animated />
    <QueryError v-else-if="isError" :error="error" @retry="refetch()" />
    <el-table v-else-if="data" :data="data.items" row-key="id">
      <el-table-column prop="name" label="姓名" min-width="120" />
      <el-table-column prop="email" label="Email" min-width="200" />
      <el-table-column label="角色" width="130">
        <template #default="{ row }">
          <el-select
            :model-value="row.role"
            size="small"
            :aria-label="`${row.name} 的角色`"
            :loading="roleMutation.isPending.value && roleMutation.variables.value?.user.id === row.id"
            @update:model-value="(role: Role) => changeRole(row, role)"
          >
            <el-option v-for="(text, value) in ROLE_LABELS" :key="value" :label="text" :value="value" />
          </el-select>
        </template>
      </el-table-column>
      <el-table-column label="狀態" width="150">
        <template #default="{ row }">
          <el-tag :type="row.status === 'active' ? 'success' : 'info'" disable-transitions>
            {{ label(USER_STATUS_LABELS, row.status) }}
          </el-tag>
          <el-tooltip v-if="row.is_locked" :content="`鎖定到 ${formatTaipei(row.locked_until)}`">
            <el-tag type="danger" class="locked" disable-transitions>鎖定中</el-tag>
          </el-tooltip>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="190">
        <template #default="{ row }">
          <el-button
            v-if="row.is_locked"
            size="small"
            type="warning"
            plain
            :loading="unlockMutation.isPending.value && unlockMutation.variables.value?.id === row.id"
            @click="unlockMutation.mutate(row)"
          >
            解除鎖定
          </el-button>
          <el-button
            v-if="row.status === 'active'"
            size="small"
            type="danger"
            plain
            :disabled="row.id === auth.user?.id"
            :loading="statusMutation.isPending.value && statusMutation.variables.value?.user.id === row.id"
            @click="disable(row)"
          >
            停用
          </el-button>
          <el-button
            v-else
            size="small"
            :loading="statusMutation.isPending.value && statusMutation.variables.value?.user.id === row.id"
            @click="enable(row)"
          >
            啟用
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="createDialog" title="建立幹部帳號" width="min(480px, 92vw)">
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent>
        <el-form-item label="Email" prop="email">
          <el-input v-model="form.email" type="email" autocomplete="off" />
        </el-form-item>
        <el-form-item label="姓名" prop="name">
          <el-input v-model="form.name" maxlength="50" />
        </el-form-item>
        <el-form-item label="角色" prop="role">
          <el-radio-group v-model="form.role">
            <el-radio-button value="writer">撰稿者</el-radio-button>
            <el-radio-button value="publisher">發佈者</el-radio-button>
            <el-radio-button value="admin">管理員</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="初始密碼" prop="initial_password">
          <el-input v-model="form.initial_password" type="password" show-password autocomplete="new-password" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialog = false">取消</el-button>
        <el-button type="primary" :loading="createMutation.isPending.value" @click="submitCreate">建立</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.locked {
  margin-left: 4px;
}
</style>
