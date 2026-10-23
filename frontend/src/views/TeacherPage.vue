<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import {
  approveCheck,
  closeCheck,
  createClassroom,
  detachQuestion,
  endClassroom,
  fetchTeacherSnapshot,
  fetchTeacherChecks,
  generateCheck,
  getJoinCode,
  getTeacherToken,
  rememberTeacherClassroom,
  saveTeacherAccess,
  retryQuestion,
  retryPendingQuestions,
  runIntegrationDrill,
  syncPolyvQuestions,
  updateClusterStatus,
  verifyPolyvContract,
  type Cluster,
  type CheckQuestion,
  type Snapshot,
} from '../services/api'

const route = useRoute()
const router = useRouter()
const snapshot = ref<Snapshot | null>(null)
const checks = ref<CheckQuestion[]>([])
const checkBusy = ref(false)
const selectedId = ref('')
const error = ref('')
const integrationMessage = ref('')
const ending = ref(false)
const creatingNext = ref(false)
const loading = ref(true)
const missingTeacherAccess = ref(false)
const copilotState = ref<'idle' | 'waiting' | 'connected' | 'unavailable'>('idle')
let copilotRequestId = ''
let copilotTimer: ReturnType<typeof window.setTimeout> | undefined
const clusters = computed(() => snapshot.value?.clusters ?? [])
const selected = computed(() => clusters.value.find((item) => item.id === selectedId.value))
const selectedCheck = computed(() => checks.value.find((item) => item.cluster_id === selectedId.value))
const participantTotal = computed(() => new Set(
  clusters.value.flatMap((cluster) => cluster.questions.map((question) => question.participant_id)),
).size)
const activeClusterTotal = computed(() => clusters.value.filter((item) => item.status !== 'closed').length)
const joinCode = computed(() => getJoinCode(String(route.params.sessionId)))
const studentJoinUrl = computed(() => `${window.location.origin}/student/${route.params.sessionId}?code=${encodeURIComponent(joinCode.value)}`)

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
  const sessionId = String(route.params.sessionId)
  const teacherToken = getTeacherToken(sessionId)
  if (!teacherToken) {
    error.value = '当前页面没有教师访问令牌，请使用教师专属入口重新打开。'
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
    const sessionId = String(route.params.sessionId)
    ;[snapshot.value, checks.value] = await Promise.all([
      fetchTeacherSnapshot(sessionId), fetchTeacherChecks(sessionId),
    ])
    rememberTeacherClassroom(sessionId, snapshot.value.title, getJoinCode(sessionId))
    if (!selectedId.value && clusters.value.length) selectedId.value = clusters.value[0].id
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '无法读取课堂'
  } finally {
    loading.value = false
  }
}

async function bootstrapTeacherAccess() {
  const fragment = new URLSearchParams(route.hash.replace(/^#/, ''))
  const access = fragment.get('access') || (typeof route.query.access === 'string' ? route.query.access : '')
  const code = fragment.get('code') || (typeof route.query.code === 'string' ? route.query.code : '')
  if (access && code) {
    saveTeacherAccess(String(route.params.sessionId), access, code)
    await router.replace({ path: route.path })
  }
  if (!getTeacherToken(String(route.params.sessionId))) {
    missingTeacherAccess.value = true
    loading.value = false
    error.value = '教师页面需要从“创建课堂”流程或教师专属入口进入，无需另行申请权限。'
    return
  }
  missingTeacherAccess.value = false
  await refresh()
}

async function detach(questionId: string) {
  error.value = ''
  try {
    await detachQuestion(String(route.params.sessionId), questionId)
    selectedId.value = ''
    await refresh()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '拆分失败'
  }
}

async function retry(questionId: string) {
  error.value = ''
  try {
    await retryQuestion(String(route.params.sessionId), questionId)
    await refresh()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '重试失败'
  }
}

async function finishClassroom() {
  if (!window.confirm('结束课堂后，学生将无法继续观看和提问，课堂数据会转为只读。确定结束吗？')) return
  error.value = ''
  ending.value = true
  try {
    await endClassroom(String(route.params.sessionId))
    integrationMessage.value = '课堂已结束，学生端已停止播放和提问。请同时在开播页面结束直播。'
    await refresh()
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
    await router.push(`/teacher/${next.id}`)
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
    const result = await verifyPolyvContract(String(route.params.sessionId))
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
  try {
    const result = await syncPolyvQuestions(String(route.params.sessionId))
    integrationMessage.value = `真实同步完成：读取 ${result.data.fetched} 条，新增 ${result.data.accepted} 条，去重 ${result.data.duplicates} 条`
    await refresh()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '真实同步失败'
    await refresh()
  }
}

async function drill(action: 'degrade' | 'recover') {
  error.value = ''
  try {
    await runIntegrationDrill(String(route.params.sessionId), action)
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
    const result = await retryPendingQuestions(String(route.params.sessionId))
    integrationMessage.value = `已尝试 ${result.data.attempted} 条，恢复 ${result.data.recovered} 条，剩余 ${result.data.remaining} 条`
    await refresh()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '批量重试失败'
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
  student: '课堂页面', local: '课堂页面', polyv_qa: '直播提问', polyv: '直播提问',
}

async function advance(cluster: Cluster) {
  error.value = ''
  try {
    await updateClusterStatus(
      String(route.params.sessionId), cluster.id, nextStatus[cluster.status], cluster.version,
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
    await generateCheck(String(route.params.sessionId), selected.value.id)
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
  checkBusy.value = true
  try {
    await approveCheck(String(route.params.sessionId), selectedCheck.value.id)
    await refresh()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '发布检测失败'
  } finally {
    checkBusy.value = false
  }
}

async function finishCheck() {
  if (!selectedCheck.value) return
  checkBusy.value = true
  try {
    await closeCheck(String(route.params.sessionId), selectedCheck.value.id)
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
})
</script>

<template>
  <main class="workspace teacher-page">
    <section v-if="!snapshot" class="surface page-state">
      <p class="eyebrow">教师工作台</p>
      <h1>{{ loading ? '正在加载课堂…' : '无法打开教师工作台' }}</h1>
      <p>{{ loading ? '正在读取课堂信息，请稍候。' : error || '请从教师专属入口重新进入课堂。' }}</p>
      <RouterLink v-if="missingTeacherAccess" class="button-link" to="/">返回首页创建课堂</RouterLink>
      <button v-else-if="!loading" @click="refresh">重新加载</button>
    </section>

    <template v-else>
    <header class="page-heading">
      <div><p class="eyebrow">教师工作台</p><h1>{{ snapshot.title }}</h1><p>{{ snapshot.status === 'ended' ? '课堂已结束 · 数据只读' : '实时汇总学生疑问与理解反馈' }}</p></div>
      <div class="connection"><span class="live-dot"></span><div><strong>{{ snapshot.status === 'ended' ? '课堂已结束' : error ? '部分功能需要处理' : snapshot.integration_status === 'degraded' ? '互动同步暂时中断' : '课堂数据已连接' }}</strong><small>{{ error || integrationMessage || (snapshot.status === 'ended' ? '可查看报告或创建下一堂课' : '新问题会自动出现在下方') }}</small></div><button @click="refresh">刷新</button><RouterLink class="button-link" :to="`/report/${route.params.sessionId}`">查看报告</RouterLink><button v-if="snapshot.status !== 'ended'" @click="syncPolyv">同步最新提问</button><button v-if="snapshot.status !== 'ended'" class="danger-action" :disabled="ending" @click="finishClassroom">{{ ending ? '正在结束…' : '结束课堂' }}</button><button v-else class="primary-action" :disabled="creatingNext" @click="createNextClassroom">{{ creatingNext ? '正在创建…' : '创建下一堂课' }}</button></div>
    </header>

    <section v-if="snapshot?.status === 'ended'" class="surface session-ended-notice">
      <div><p class="eyebrow">课堂已结束</p><strong>本堂课的数据已保存</strong><small>学生端已经停止播放和提问。如开播页面仍在推流，请回到开播页面点击“结束直播”。</small></div>
    </section>

    <section v-if="snapshot?.status !== 'ended' && joinCode" class="surface classroom-access-panel">
      <div><p class="eyebrow">学生入口</p><strong>课堂码 {{ joinCode }}</strong><small>将学生入口或课堂码发给学生，即可加入本堂课。</small></div>
      <div class="classroom-access-actions">
        <a :href="studentJoinUrl" target="_blank" rel="noreferrer">打开学生入口</a>
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
