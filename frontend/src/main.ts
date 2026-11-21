import 'element-plus/dist/index.css'
import './shared/styles.css'

import { MutationCache, QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import ElementPlus, { ElMessage } from 'element-plus'
import zhTw from 'element-plus/es/locale/lang/zh-tw'
import { createPinia } from 'pinia'
import { createApp } from 'vue'

import App from './App.vue'
import { installAuthHooks } from './shared/api/client'
import { ApiError, errorMessage } from './shared/api/errors'
import { useAuthStore } from './shared/auth'
import { redirectToLogin, router } from './shared/router'

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // 4xx 是確定的錯誤，重試也不會變；只有連線問題與 5xx 重試一次
      retry: (count, error) => count < 1 && (!(error instanceof ApiError) || error.status === 0 || error.status >= 500),
      refetchOnWindowFocus: false,
    },
  },
  // 所有寫入操作的錯誤統一用 ElMessage 顯示中文提示；401 已導回登入頁，不另外顯示
  mutationCache: new MutationCache({
    onError: (error) => {
      if (error instanceof ApiError && error.status === 401 && error.code === 'UNAUTHENTICATED') return
      ElMessage.error({ message: errorMessage(error), duration: 5000 })
    },
  }),
})

// Access Token 過期時先換發；換發也失敗代表登入已失效，清掉快取，下一位登入的人不會看到上一位的資料
const auth = useAuthStore(pinia)
installAuthHooks({
  getToken: () => auth.token,
  refresh: () => auth.refresh(),
  onUnauthenticated: () => {
    queryClient.clear()
    redirectToLogin()
  },
})

app.use(VueQueryPlugin, { queryClient })
app.use(ElementPlus, { locale: zhTw })
app.use(router)
app.mount('#app')
