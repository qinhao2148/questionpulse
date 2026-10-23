<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import ReportPage from './ReportPage.vue'

import {
  approveCheck,
  closeCheck,
  createClassroom,
  detachQuestion,
  endClassroom,
  fetchTeacherSnapshot,
  fetchTeacherChecks,
  fetchChatReviewQueue,
  generateCheck,
  getTeacherAccessToken,
  hasTeacherAccess,
  retryQuestion,
  retryPendingQuestions,
  reviewChatMessage,
  runIntegrationDrill,
  syncPolyvChatMessages,
  syncPolyvQuestions,
  updateClusterStatus,
  updateJoinCode,
  verifyPolyvContract,
  type Cluster,
  type CheckQuestion,
  type ChatReviewItem,
  type Snapshot,
  TEACHER_LOGIN_REQUIRED_MESSAGE,
} from '../services/api'

const props = defineProps<{ sessionId: string }>()
const emit = defineEmits<{ close: []; openSession: [sessionId: string] }>()
const snapshot = ref<Snapshot | null>(null)
const checks = ref<CheckQuestion[]>([])
const chatReviewQueue = ref<ChatReviewItem[]>([])
const checkBusy = ref(false)
const selectedId = ref('')
const error = ref('')
const integrationMessage = ref('')
const ending = ref(false)
const creatingNext = ref(false)
const joinCodeDraft = ref('')
const joinCodeDirty = ref(false)
const savingJoinCode = ref(false)
const showingReport = ref(false)
const loading = ref(true)
const missingTeacherAccess = ref(false)
const copilotState = ref<'idle' | 'waiting' | 'connected' | 'unavailable'>('idle')
let copilotRequestId = ''
let copilotTimer: number | undefined
let pollTimer: number | undefined
// Students ask questions continuously while the lesson runs, so the workbench
// has to follow along. It used to require a manual refresh even though the
// header promised new questions would show up on their own.
// A snapshot costs ~12ms server-side, so 3s keeps the panel feeling live without
// measurable load; the POLYV pull is throttled separately by AUTO_SYNC_INTERVAL_MS.
const POLL_INTERVAL_MS = 3000
const clusters = computed(() => snapshot.value?.clusters ?? [])
const selected = computed(() => clusters.value.find((item) => item.id === selectedId.value))
// A check belongs to one feedback round. Matching only on the cluster id made
// round two reuse round one's finished check, which hid the "生成理解检测题"
// button for the rest of the lesson.
const selectedCheck = computed(() => checks.value.find(
  (item) => item.cluster_id === selectedId.value
    && item.feedback_round === (selected.value?.feedback_round ?? 0),
))
const pastChecks = computed(() => checks.value.filter(
  (item) => item.cluster_id === selectedId.value
    && item.feedback_round !== (selected.value?.feedback_round ?? 0),
))
const participantTotal = computed(() => new Set(
  clusters.value.flatMap((cluster) => cluster.questions.map((question) => question.participant_id)),
).size)
const activeClusterTotal = computed(() => clusters.value.filter((item) => item.status !== 'closed').length)
// "课堂数据已连接" used to show even for a classroom that never talked to POLYV,
// which made the teacher believe live sync was on when only local questions worked.
const connectionTitle = computed(() => {
  if (snapshot.value?.status === 'ended') return '课堂已结束'
  if (error.value) return '部分功能需要处理'
  const status = snapshot.value?.integration_status
  if (status === 'degraded') return '互动同步暂时中断'
  if (status === 'connected') return '直播互动已连接'
  if (status === 'contract_verified') return '接入验证已完成'
  return '课堂提问已就绪'
})
const joinCode = computed(() => snapshot.value?.join_code || '')
const studentJoinUrl = computed(() => {
  const base = import.meta.env.VITE_POLYV_WATCH_BASE_URL || 'http://127.0.0.1:15021/index.html'
  const query = new URLSearchParams({ qpJoin: '1', qpApiBase: import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000/api/v1' })
  return `${base}?${query.toString()}`
})

function handleCopilotPairing(event: MessageEvent) {
  const message = event.data
  if (event.source !== window || event.origin !== window.location.origin
    || message?.source !== 'questionpulse-copilot-extension'
    || message?.type !== 'QUESTIONPULSE_BIND_RESULT'
    || message?.requestId !== copilotRequestId) return
  if (copilotTimer) window.clearTimeout(copilotTimer)
  copilotState.value = message.ok ? 'connected' : 'unavailable'
  integrationMessage.value = message.ok
    ? '开播助手已绑定本课堂；返回或刷新保利威开播页即可显示已连接。'
    : '扩展未能完成绑定，请确认扩展已启用并重新加载。'
}

function connectCopilot() {
  const sessionId = props.sessionId
  const teacherToken = getTeacherAccessToken()
  if (!teacherToken) {
    error.value = '请先返回教师课堂中心登录。'
    return
  }
  copilotState.value = 'waiting'
  copilotRequestId = crypto.randomUUID()
  const backendHost = window.location.hostname === 'localhost' ? 'localhost' : '127.0.0.1'
  window.postMessage({
    source: 'questionpulse-teacher-app',
    type: 'QUESTIONPULSE_BIND_COPILOT',
    requestId: copilotRequestId,
    payload: {
      apiBaseUrl: `http://${backendHost}:8000/api/v1`,
      webBaseUrl: window.location.origin,
      sessionId,
      teacherToken,
    },
  }, window.location.origin)
  if (copilotTimer) window.clearTimeout(copilotTimer)
  copilotTimer = window.setTimeout(() => {
    if (copilotState.value === 'waiting') {
      copilotState.value = 'unavailable'
      integrationMessage.value = '没有检测到开播助手，请在 Edge 扩展页启用或重新加载扩展。'
    }
  }, 1800)
}

async function refresh() {
  error.value = ''
  try {
    const sessionId = props.sessionId
    ;[snapshot.value, checks.value, chatReviewQueue.value] = await Promise.all([
      fetchTeacherSnapshot(sessionId), fetchTeacherChecks(sessionId), fetchChatReviewQueue(sessionId),
    ])
    // Polling must not overwrite the classroom code while the teacher is typing
    // a replacement into the input.
    if (!joinCodeDirty.value) joinCodeDraft.value = snapshot.value.join_code || ''
    if (!selectedId.value && clusters.value.length) selectedId.value = clusters.value[0].id
  } catch (reason) {
    const message = reason instanceof Error ? reason.message : '无法读取课堂'
    if (message === TEACHER_LOGIN_REQUIRED_MESSAGE) {
      // The token has been dropped by the request layer; send the teacher back
      // to the console instead of stranding them on a read-only error page.
      missingTeacherAccess.value = true
      emit('close')
      return
    }
    error.value = message
  } finally {
    loading.value = false
  }
}

function stopPolling() {
  if (pollTimer) window.clearInterval(pollTimer)
  pollTimer = undefined
  if (settleTimer) window.clearTimeout(settleTimer)
  settleTimer = undefined
}

function startPolling() {
  stopPolling()
  // A finished classroom is read-only, and a hidden tab should not keep hitting
  // the API. Both resume the moment the teacher is back on a live classroom.
  pollTimer = window.setInterval(() => {
    if (document.hidden || showingReport.value) return
    if (snapshot.value?.status === 'ended') return
    // One tick at a time: a POLYV pull can outlast the interval, and overlapping
    // ticks would queue duplicate requests behind the same endpoint.
    if (pollBusy) return
    pollBusy = true
    void (async () => {
      try {
        const pulled = await autoPullChat()
        await refresh()
        if (!pulled) return
        // Classification starts only after the sync response is sent, so the
        // snapshot we just fetched still carries the message as pending. Look
        // again once the model has had time to finish, instead of making the
        // teacher wait for the next full tick.
        settleTimer = window.setTimeout(() => {
          if (!document.hidden && !showingReport.value) void refresh()
        }, SETTLE_REFRESH_MS)
      } finally {
        pollBusy = false
      }
    })()
  }, POLL_INTERVAL_MS)
}

// POLYV 只提供聊天历史的拉取接口，学生的消息不会主动推到我们这边。
// 不自动拉一次，界面就会一直空空如也，看起来像「没有记录」。
// 6 秒是折中：一次同步约 300ms，DeepSeek 分类约 1.8 秒，再密就开始压官方限流。
const AUTO_SYNC_INTERVAL_MS = 6_000
const SETTLE_REFRESH_MS = 2_500
let lastAutoSyncAt = 0
let pollBusy = false
let settleTimer: number | undefined

async function autoPullChat(): Promise<boolean> {
  if (Date.now() - lastAutoSyncAt < AUTO_SYNC_INTERVAL_MS) return false
  // 先打时间戳：接口失败时不要每个 tick 都重试一次。
  lastAutoSyncAt = Date.now()
  try {
    await syncPolyvChatMessages(props.sessionId)
    return true
  } catch {
    // 手动「同步聊天与提问」会把原因显示出来，后台轮询保持安静。
    return false
  }
}

async function saveJoinCode() {
  const code = joinCodeDraft.value.trim().toUpperCase()
  if (code.length < 4) return
  savingJoinCode.value = true
  error.value = ''
  try {
    await updateJoinCode(props.sessionId, code)
    joinCodeDirty.value = false
    await refresh()
  }
  catch (reason) { error.value = reason instanceof Error ? reason.message : '课堂码保存失败' }
  finally { savingJoinCode.value = false }
}

async function bootstrapTeacherAccess() {
  if (!hasTeacherAccess()) {
    missingTeacherAccess.value = true
    loading.value = false
    error.value = '请先返回教师课堂中心登录。'
    return
  }
  missingTeacherAccess.value = false
  await refresh()
  if (snapshot.value && snapshot.value.status !== 'ended') startPolling()
}

async function detach(questionId: string) {
  error.value = ''
  try {
    await detachQuestion(props.sessionId, questionId)
    selectedId.value = ''
    await refresh()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '拆分失败'
  }
}

async function retry(questionId: string) {
  error.value = ''
  try {
    await retryQuestion(props.sessionId, questionId)
    await refresh()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '重试失败'
  }
}

async function finishClassroom() {
  // 结束课堂只关闭提问、反馈和检测，不会停止 POLYV 里的推流/观看。
  if (!window.confirm('结束课堂后，学生将无法继续提问、提交反馈或作答，课堂数据会转为只读。确定结束吗？')) return
  error.value = ''
  ending.value = true
  try {
    await endClassroom(props.sessionId)
    integrationMessage.value = '课堂已结束，学生端已停止接收提问与反馈。请同时在开播页面结束直播。'
    await refresh()
    stopPolling()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '结束课堂失败'
  } finally {
    ending.value = false
  }
}

async function createNextClassroom() {
  creatingNext.value = true
  error.value = ''
  try {
    const next = await createClassroom(`${snapshot.value?.title || 'QuestionPulse 课堂'} · 新课堂`)
    emit('openSession', next.id)
    selectedId.value = ''
    integrationMessage.value = '新课堂已创建，上一堂课的报告保持不变。'
    await refresh()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '创建新课堂失败'
  } finally {
    creatingNext.value = false
  }
}

async function verifyContract() {
  error.value = ''
  integrationMessage.value = ''
  try {
    const result = await verifyPolyvContract(props.sessionId)
    integrationMessage.value = result.data.accepted
      ? `契约验证成功：导入 ${result.data.accepted} 条，跳过 ${result.data.duplicates} 条重复数据`
      : `契约验证成功：${result.data.duplicates} 条数据均已去重`
    await refresh()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '契约验证失败'
  }
}

async function syncPolyv() {
  error.value = ''
  integrationMessage.value = ''
  const sessionId = props.sessionId
  // Chat history and the Q&A list are independent POLYV endpoints. Running them
  // one after another meant a chat-sync failure also skipped the questions.
  const [chatResult, questionResult] = await Promise.allSettled([
    syncPolyvChatMessages(sessionId), syncPolyvQuestions(sessionId),
  ])
  const parts: string[] = []
  if (chatResult.status === 'fulfilled') {
    parts.push(`聊天新增 ${chatResult.value.data.accepted} 条、去重 ${chatResult.value.data.duplicates} 条`)
  } else {
    parts.push(`聊天同步失败（${chatResult.reason instanceof Error ? chatResult.reason.message : '未知错误'}）`)
  }
  if (questionResult.status === 'fulfilled') {
    parts.push(`提问新增 ${questionResult.value.data.accepted} 条、去重 ${questionResult.value.data.duplicates} 条`)
  } else {
    parts.push(`提问同步失败（${questionResult.reason instanceof Error ? questionResult.reason.message : '未知错误'}）`)
  }
  const failed = chatResult.status === 'rejected' || questionResult.status === 'rejected'
  if (failed) error.value = parts.join('；')
  else integrationMessage.value = `真实同步完成：${parts.join('；')}`
  // A manual pull has the same lag as the background one: the model only starts
  // after the response, so the first refresh still lists nothing new.
  lastAutoSyncAt = Date.now()
  await refresh()
  if (settleTimer) window.clearTimeout(settleTimer)
  settleTimer = window.setTimeout(() => {
    if (!document.hidden) void refresh()
  }, SETTLE_REFRESH_MS)
}

async function drill(action: 'degrade' | 'recover') {
  error.value = ''
  try {
    await runIntegrationDrill(props.sessionId, action)
    integrationMessage.value = action === 'degrade'
      ? '已进入本地降级演练：课堂业务继续可用'
      : '本地接入状态已恢复'
    await refresh()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '演练操作失败'
  }
}

async function retryAll() {
  error.value = ''
  try {
    const result = await retryPendingQuestions(props.sessionId)
    integrationMessage.value = `已尝试 ${result.data.attempted} 条，恢复 ${result.data.recovered} 条，剩余 ${result.data.remaining} 条`
    await refresh()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '批量重试失败'
  }
}

async function decideChat(item: ChatReviewItem, action: 'promote' | 'ignore') {
  error.value = ''
  try {
    await reviewChatMessage(props.sessionId, item.id, action)
    integrationMessage.value = action === 'promote' ? '聊天已收录为疑问并进入聚类。' : '聊天已标记为普通消息。'
    await refresh()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '聊天审核失败'
  }
}

const nextStatus: Record<string, string> = {
  open: 'addressing',
  addressing: 'awaiting_feedback',
  awaiting_feedback: 'closed',
  closed: 'open',
}
const actionLabel: Record<string, string> = {
  open: '开始讲解',
  addressing: '结束讲解并收集反馈',
  awaiting_feedback: '关闭疑问',
  closed: '重新打开',
}
const statusLabel: Record<string, string> = {
  open: '待处理', addressing: '讲解中', awaiting_feedback: '等待反馈', closed: '已关闭',
}
const sourceLabel: Record<string, string> = {
  student: '课堂页面', local: '课堂页面', polyv_qa: '直播提问', polyv: '直播提问', polyv_chat: '直播聊天',
}

async function advance(cluster: Cluster) {
  error.value = ''
  try {
    await updateClusterStatus(
      props.sessionId, cluster.id, nextStatus[cluster.status], cluster.version,
    )
    await refresh()
  } catch (reason) {
    error.value = reason instanceof Error ? `${reason.message}，请刷新后重试` : '状态修改失败'
  }
}

async function createCheck() {
  if (!selected.value) return
  checkBusy.value = true
  error.value = ''
  try {
    await generateCheck(props.sessionId, selected.value.id)
    integrationMessage.value = '理解检测草稿已生成，请审核答案与解释后再发布。'
    await refresh()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '生成检测失败'
  } finally {
    checkBusy.value = false
  }
}

async function publishCheck() {
  if (!selectedCheck.value) return
  if (!window.confirm('发布后这道题会立刻出现在相关学生的课堂页面上，确定发布吗？')) return
  checkBusy.value = true
  try {
    await approveCheck(props.sessionId, selectedCheck.value.id)
    await refresh()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '发布检测失败'
  } finally {
    checkBusy.value = false
  }
}

async function finishCheck() {
  if (!selectedCheck.value) return
  if (!window.confirm('结束检测后学生将无法继续作答，已提交的答案会保留。确定结束吗？')) return
  checkBusy.value = true
  try {
    await closeCheck(props.sessionId, selectedCheck.value.id)
    await refresh()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '关闭检测失败'
  } finally {
    checkBusy.value = false
  }
}

onMounted(() => {
  window.addEventListener('message', handleCopilotPairing)
  bootstrapTeacherAccess()
})
onBeforeUnmount(() => {
  window.removeEventListener('message', handleCopilotPairing)
  if (copilotTimer) window.clearTimeout(copilotTimer)
  stopPolling()
})
</script>

<template>
  <main class="workspace teacher-page" :class="{ 'showing-report': showingReport }">
    <section v-if="!snapshot" class="surface page-state">
      <p class="eyebrow">教师工作台</p>
      <h1>{{ loading ? '正在加载课堂…' : '无法打开教师工作台' }}</h1>
      <p>{{ loading ? '正在读取课堂信息，请稍候。' : error || '请从教师课堂中心重新进入。' }}</p>
      <button v-if="missingTeacherAccess" class="button-link" @click="emit('close')">返回课堂列表</button>
      <button v-else-if="!loading" @click="refresh">重新加载</button>
    </section>

    <template v-else>
    <header class="page-heading">
      <div><p class="eyebrow">教师工作台</p><h1>{{ snapshot.title }}</h1><p>{{ snapshot.status === 'ended' ? '课堂已结束 · 数据只读' : '实时汇总学生疑问与理解反馈' }}</p></div>
      <div class="connection"><span class="live-dot"></span><div><strong>{{ connectionTitle }}</strong><small>{{ error || integrationMessage || (snapshot.status === 'ended' ? '可查看报告或创建下一堂课' : '新问题会自动出现在下方') }}</small></div><button @click="emit('close')">课堂列表</button><button @click="refresh">刷新</button><button class="button-link" @click="showingReport = !showingReport">{{ showingReport ? '收起报告' : '课堂报告' }}</button><button v-if="snapshot.status !== 'ended'" @click="syncPolyv">同步聊天与提问</button><button v-if="snapshot.status !== 'ended'" class="danger-action" :disabled="ending" @click="finishClassroom">{{ ending ? '正在结束…' : '结束课堂' }}</button><button v-else class="primary-action" :disabled="creatingNext" @click="createNextClassroom">{{ creatingNext ? '正在创建…' : '创建下一堂课' }}</button></div>
    </header>

    <ReportPage v-if="showingReport" :session-id="props.sessionId" />

    <section v-if="snapshot?.status === 'ended'" class="surface session-ended-notice">
      <div><p class="eyebrow">课堂已结束</p><strong>本堂课的数据已保存</strong><small>学生端已经停止接收提问、反馈和检测作答。直播画面仍由保利威播放，请回到开播页面点击“结束直播”。</small></div>
    </section>

    <section v-if="snapshot?.status !== 'ended' && joinCode" class="surface classroom-access-panel">
      <div><p class="eyebrow">学生入口</p><strong>课堂码 {{ joinCode }}</strong><small>学生打开统一学生端，输入课堂码和访问名称即可加入。</small></div>
      <div class="classroom-access-actions">
        <input v-model="joinCodeDraft" maxlength="12" aria-label="设置课堂码" placeholder="设置课堂码" @input="joinCodeDirty = true" />
        <button type="button" :disabled="savingJoinCode || joinCodeDraft.trim().length < 4" @click="saveJoinCode">{{ savingJoinCode ? '保存中…' : '保存课堂码' }}</button>
        <a :href="studentJoinUrl" target="_blank" rel="noreferrer">打开学生端</a>
        <button type="button" :disabled="copilotState === 'waiting'" @click="connectCopilot">{{ copilotState === 'waiting' ? '正在连接…' : copilotState === 'connected' ? '开播助手已连接' : '连接开播助手' }}</button>
      </div>
      <p v-if="copilotState === 'connected'" class="copilot-success">连接成功。开播页面右下角的 QP 助手会显示本课堂疑问。</p>
    </section>

    <section class="surface reliability-panel" :class="{ degraded: snapshot.integration_status === 'degraded' }">
      <div><p class="eyebrow">互动状态</p><strong>{{ snapshot.integration_status === 'degraded' ? '同步暂时中断，课堂提问仍可使用' : snapshot.integration_status === 'connected' ? '直播互动已连接' : '课堂提问已就绪' }}</strong><small v-if="snapshot.integration_status === 'connected'">最近同步 {{ snapshot.last_synced_at ? new Date(snapshot.last_synced_at).toLocaleTimeString('zh-CN') : '尚无' }}</small><small v-else>学生提交的问题会保存在本课堂中</small></div>
    </section>

    <section class="metrics-grid">
      <article><span>提问学生</span><strong>{{ participantTotal }}</strong><small>按独立学生统计</small></article>
      <article><span>疑问主题</span><strong>{{ clusters.length }}</strong><small>相似问题自动汇总</small></article>
      <article><span>问题总数</span><strong>{{ clusters.reduce((sum, item) => sum + item.question_count, 0) }}</strong><small>已自动过滤重复提交</small></article>
      <article><span>仍需关注</span><strong>{{ activeClusterTotal }}</strong><small>{{ snapshot.pending_questions.length }} 条问题等待重新处理</small></article>
    </section>

    <section v-if="chatReviewQueue.length" class="surface pending-panel">
      <div class="pending-heading"><div><p class="eyebrow">AI 待确认</p><h2>可能是课程疑问的聊天</h2></div><span>{{ chatReviewQueue.length }} 条</span></div>
      <div v-for="item in chatReviewQueue" :key="item.id" class="pending-row">
        <span><strong>{{ item.content }}</strong><small>建议：{{ item.suggested_question || item.normalized_intent }} · 置信度 {{ Math.round(item.confidence * 100) }}%</small></span>
        <div><button @click="decideChat(item, 'promote')">收录为疑问</button><button @click="decideChat(item, 'ignore')">忽略</button></div>
      </div>
    </section>

    <div class="dashboard-grid">
      <section class="cluster-list">
        <button v-for="cluster in clusters" :key="cluster.id" class="surface cluster-card" :class="{ selected: selectedId === cluster.id }" @click="selectedId = cluster.id">
          <div class="card-row"><span class="status" :class="cluster.status">{{ statusLabel[cluster.status] }}</span><span>困惑指数 {{ cluster.confusion_score }}</span></div>
          <h2>{{ cluster.title }}</h2>
          <div class="cluster-stats"><strong>{{ cluster.participant_count }}</strong> 人同问 <span>·</span> {{ cluster.question_count }} 条原始问题 <span>·</span> {{ cluster.confusion_level === 'high' ? '建议优先讲解' : cluster.confusion_level === 'medium' ? '建议关注' : '状态平稳' }}</div>
          <div v-if="cluster.feedback.targets" class="feedback-meter"><i :style="{ width: `${cluster.feedback.responses / cluster.feedback.targets * 100}%` }"></i></div>
        </button>
        <p v-if="!clusters.length" class="empty-state">暂无问题，请先从学生端提交。</p>
      </section>

      <aside v-if="selected" class="surface detail-panel">
        <p class="eyebrow">主题详情</p><h2>{{ selected.title }}</h2>
        <div class="impact-number"><strong>{{ selected.participant_count }}</strong><span>名独立学生受到影响</span></div>
        <details class="confusion-detail"><summary>困惑指数 {{ selected.confusion_score }} 的计算依据</summary><div><span>参与学生比例 {{ Math.round(selected.confusion_breakdown.participant_ratio * 100) }}%</span><span>最近问题强度 {{ Math.round(selected.confusion_breakdown.recent_activity * 100) }}%</span><span>等待压力 {{ Math.round(selected.confusion_breakdown.wait_pressure * 100) }}%</span><span>仍困惑比例 {{ Math.round(selected.confusion_breakdown.still_confused_ratio * 100) }}%</span><span>检测错误率 {{ Math.round(selected.confusion_breakdown.check_error_ratio * 100) }}%</span></div></details>
        <div v-if="selected.feedback.targets" class="feedback-summary">
          <span>反馈 {{ selected.feedback.responses }}/{{ selected.feedback.targets }}</span>
          <span class="good-text">已理解 {{ selected.feedback.understood }}</span>
          <span class="warn-text">仍困惑 {{ selected.feedback.still_confused }}</span>
        </div>
        <h3>原始表达</h3>
        <ul class="question-list"><li v-for="question in selected.questions" :key="question.id"><span>{{ question.content }} <small>来自{{ sourceLabel[question.source] || '课堂提问' }}</small></span><button :disabled="snapshot.status === 'ended' || selected.questions.length < 2" @click="detach(question.id)">移出当前主题</button></li></ul>
        <div v-if="snapshot?.status !== 'ended'" class="action-stack">
          <button class="primary-action" :disabled="selected.status === 'awaiting_feedback' && selectedCheck?.status === 'active'" @click="advance(selected)">{{ actionLabel[selected.status] }}</button>
          <p v-if="selected.status === 'awaiting_feedback' && selectedCheck?.status === 'active'" class="mode-note">请先结束正在进行的理解检测，再关闭这个疑问。</p>
        </div>
        <section v-if="selected.feedback_round > 0" class="check-teacher-panel">
          <div class="card-row"><h3>理解检测</h3><span v-if="selectedCheck">{{ selectedCheck.status === 'draft' ? '待审核' : selectedCheck.status === 'active' ? '答题中' : '已关闭' }}</span></div>
          <template v-if="selectedCheck">
            <p class="check-stem">{{ selectedCheck.stem }}</p>
            <ol class="check-review-options"><li v-for="option in selectedCheck.options" :key="option.key" :class="{ correct: option.key === selectedCheck.correct_option_key }">{{ option.key }}. {{ option.content }}</li></ol>
            <p class="mode-note">正确答案 {{ selectedCheck.correct_option_key }} · {{ selectedCheck.explanation }}</p>
            <p v-if="selectedCheck.status !== 'draft'">作答 {{ selectedCheck.response_count }}/{{ selectedCheck.target_count }} · 正确 {{ selectedCheck.correct_count }}</p>
            <button v-if="selectedCheck.status === 'draft'" :disabled="checkBusy" @click="publishCheck">确认并发布给相关学生</button>
            <button v-else-if="selectedCheck.status === 'active'" :disabled="checkBusy" @click="finishCheck">结束检测</button>
          </template>
          <button v-else-if="selected.status === 'awaiting_feedback'" :disabled="checkBusy" @click="createCheck">生成理解检测题</button>
          <p v-else-if="!selectedCheck" class="mode-note">结束本轮讲解并进入反馈阶段后，可生成一道检测题。</p>
          <details v-if="pastChecks.length" class="past-checks">
            <summary>前几轮的检测（{{ pastChecks.length }} 道）</summary>
            <div v-for="item in pastChecks" :key="item.id" class="past-check-row">
              <p class="check-stem">第 {{ item.feedback_round }} 轮 · {{ item.stem }}</p>
              <p class="mode-note">作答 {{ item.response_count }}/{{ item.target_count }} · 正确 {{ item.correct_count }} · {{ item.status === 'closed' ? '已结束' : item.status === 'active' ? '答题中' : '待审核' }}</p>
            </div>
          </details>
        </section>
      </aside>
    </div>
    <section v-if="snapshot?.status !== 'ended' && snapshot?.pending_questions.length" class="surface pending-panel">
      <div class="pending-heading"><div><p class="eyebrow">需要处理</p><h2>暂未完成分析的问题</h2></div><button @click="retryAll">重新分析全部</button></div>
      <div v-for="item in snapshot.pending_questions" :key="item.id" class="pending-row"><span>{{ item.content }}</span><button @click="retry(item.id)">重新处理</button></div>
    </section>
    <details v-if="snapshot.status !== 'ended'" class="diagnostic-panel">
      <summary>接入诊断</summary>
      <p>仅在接入配置或现场验收时使用。</p>
      <div class="reliability-actions"><button @click="verifyContract">检查数据接入</button><button v-if="snapshot.integration_status !== 'degraded'" @click="drill('degrade')">测试断线保护</button><button v-else @click="drill('recover')">恢复连接状态</button></div>
    </details>
    </template>
  </main>
</template>
