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
const copilotState = ref<'idle' | 'waiting' | 'connected' | 'unavailable'>('idle')
let copilotRequestId = ''
let copilotTimer: ReturnType<typeof window.setTimeout> | undefined
const clusters = computed(() => snapshot.value?.clusters ?? [])
const selected = computed(() => clusters.value.find((item) => item.id === selectedId.value))
const selectedCheck = computed(() => checks.value.find((item) => item.cluster_id === selectedId.value))
const participantTotal = computed(() => new Set(
  clusters.value.flatMap((cluster) => cluster.questions.map((question) => question.participant_id)),
).size)
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
  try {
    const sessionId = String(route.params.sessionId)
    ;[snapshot.value, checks.value] = await Promise.all([
      fetchTeacherSnapshot(sessionId), fetchTeacherChecks(sessionId),
    ])
    if (!selectedId.value && clusters.value.length) selectedId.value = clusters.value[0].id
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '无法读取课堂'
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
  error.value = ''
  ending.value = true
  try {
    await endClassroom(String(route.params.sessionId))
    integrationMessage.value = '课堂记录已归档；学生端已停止显示直播。保利威推流需在开播控制台结束。'
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
    <header class="page-heading">
      <div><p class="eyebrow">LIVE QUESTION RADAR</p><h1>课堂疑问脉搏</h1><p>{{ snapshot?.status === 'ended' ? '课堂已归档 · 数据只读' : `${snapshot?.mode === 'demo' ? '本地演示模式' : snapshot?.mode} · ${snapshot?.integration_status === 'not_configured' ? 'POLYV 待配置' : snapshot?.integration_status === 'contract_verified' ? 'POLYV 契约已验证（未连接真实账号）' : snapshot?.integration_status === 'degraded' ? 'POLYV 接入已降级' : snapshot?.integration_status}` }}</p></div>
      <div class="connection"><span class="live-dot"></span><div><strong>{{ snapshot?.status === 'ended' ? '课堂记录已归档' : error ? '接入需要处理' : snapshot?.integration_status === 'connected' ? 'POLYV 真实数据已连接' : '本地数据已连接' }}</strong><small>{{ error || integrationMessage || (snapshot?.status === 'ended' ? '报告已冻结，可创建下一堂课' : '点击刷新读取最新问题') }}</small></div><button @click="refresh">刷新</button><RouterLink class="button-link" :to="`/report/${route.params.sessionId}`">教师报告</RouterLink><button v-if="snapshot?.status !== 'ended'" @click="syncPolyv">同步 POLYV 问答</button><button v-if="snapshot?.status !== 'ended'" @click="verifyContract">验证契约</button><button v-if="snapshot?.status !== 'ended'" class="danger-action" :disabled="ending" @click="finishClassroom">{{ ending ? '正在结束…' : '结束课堂记录' }}</button><button v-else class="primary-action" :disabled="creatingNext" @click="createNextClassroom">{{ creatingNext ? '正在创建…' : '创建下一堂课' }}</button></div>
    </header>

    <section v-if="snapshot?.status === 'ended'" class="surface session-ended-notice">
      <div><p class="eyebrow">SESSION ARCHIVED</p><strong>这堂课已结束，数据保持只读</strong><small>QuestionPulse 已关闭学生端直播与提问。保利威主播控制台是独立推流端，如仍在推流，请在该控制台点击“结束直播”。</small></div>
    </section>

    <section v-if="snapshot?.status !== 'ended' && joinCode" class="surface classroom-access-panel">
      <div><p class="eyebrow">STUDENT ACCESS</p><strong>学生课堂码 {{ joinCode }}</strong><small>分享学生链接即可加入；学生端不会显示教师控制与完整报告入口。</small></div>
      <div class="classroom-access-actions">
        <a :href="studentJoinUrl" target="_blank" rel="noreferrer">打开学生入口</a>
        <button type="button" :disabled="copilotState === 'waiting'" @click="connectCopilot">{{ copilotState === 'waiting' ? '正在连接…' : copilotState === 'connected' ? '开播助手已连接' : '连接开播助手' }}</button>
      </div>
    </section>

    <section class="surface reliability-panel" :class="{ degraded: snapshot?.integration_status === 'degraded' }">
      <div><p class="eyebrow">RELIABILITY</p><strong>{{ snapshot?.integration_status === 'degraded' ? '接入已降级，课堂本地闭环仍可使用' : snapshot?.integration_status === 'connected' ? '真实 POLYV API 已连接' : '演示保护已启用' }}</strong><small v-if="snapshot?.integration_error">{{ snapshot.integration_error }}</small><small v-else-if="snapshot?.integration_status === 'connected'">频道 {{ snapshot.polyv_channel_id }} · 最近同步 {{ snapshot.last_synced_at }}</small><small v-else>可先验证契约，配置密钥后执行真实同步</small></div>
      <div v-if="snapshot?.status !== 'ended'" class="reliability-actions"><button v-if="snapshot?.integration_status !== 'degraded'" @click="drill('degrade')">模拟接入断连</button><button v-else @click="drill('recover')">恢复接入状态</button></div>
    </section>

    <section class="metrics-grid">
      <article><span>提问学生计数</span><strong>{{ participantTotal }}</strong><small>按疑问簇实时汇总</small></article>
      <article><span>疑问簇</span><strong>{{ clusters.length }}</strong><small>{{ snapshot?.pending_questions.length || 0 }} 条待处理</small></article>
      <article><span>问题总数</span><strong>{{ clusters.reduce((sum, item) => sum + item.question_count, 0) }}</strong><small>幂等提交已启用</small></article>
      <article class="pulse-viz"><span>实时疑问强度</span><div class="bars"><i v-for="height in [24,36,28,54,76,48,88,62,40,30]" :key="height" :style="{ height: `${height}%` }"></i></div></article>
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
        <p class="eyebrow">CLUSTER DETAIL</p><h2>{{ selected.title }}</h2>
        <div class="impact-number"><strong>{{ selected.participant_count }}</strong><span>名独立学生受到影响</span></div>
        <details class="confusion-detail"><summary>困惑指数 {{ selected.confusion_score }} 的计算依据</summary><div><span>参与学生比例 {{ Math.round(selected.confusion_breakdown.participant_ratio * 100) }}%</span><span>最近问题强度 {{ Math.round(selected.confusion_breakdown.recent_activity * 100) }}%</span><span>等待压力 {{ Math.round(selected.confusion_breakdown.wait_pressure * 100) }}%</span><span>仍困惑比例 {{ Math.round(selected.confusion_breakdown.still_confused_ratio * 100) }}%</span><span>检测错误率 {{ Math.round(selected.confusion_breakdown.check_error_ratio * 100) }}%</span></div></details>
        <div v-if="selected.feedback.targets" class="feedback-summary">
          <span>反馈 {{ selected.feedback.responses }}/{{ selected.feedback.targets }}</span>
          <span class="good-text">已理解 {{ selected.feedback.understood }}</span>
          <span class="warn-text">仍困惑 {{ selected.feedback.still_confused }}</span>
        </div>
        <h3>原始表达</h3>
        <ul class="question-list"><li v-for="question in selected.questions" :key="question.id"><span>{{ question.content }} <small>· {{ question.source }}{{ question.external_id ? ` / ${question.external_id}` : '' }} · {{ question.assignment_method }}</small></span><button :disabled="snapshot?.status === 'ended' || selected.questions.length < 2" @click="detach(question.id)">拆分此题</button></li></ul>
        <div v-if="snapshot?.status !== 'ended'" class="action-stack">
          <button class="primary-action" @click="advance(selected)">{{ actionLabel[selected.status] }}</button>
        </div>
        <section v-if="selected.feedback_round > 0" class="check-teacher-panel">
          <div class="card-row"><h3>理解检测</h3><span v-if="selectedCheck">{{ selectedCheck.status === 'draft' ? '待审核' : selectedCheck.status === 'active' ? '答题中' : '已关闭' }}</span></div>
          <template v-if="selectedCheck">
            <p class="check-stem">{{ selectedCheck.stem }}</p>
            <ol class="check-review-options"><li v-for="option in selectedCheck.options" :key="option.key" :class="{ correct: option.key === selectedCheck.correct_option_key }">{{ option.key }}. {{ option.content }}</li></ol>
            <p class="mode-note">正确答案 {{ selectedCheck.correct_option_key }} · {{ selectedCheck.explanation }}</p>
            <p v-if="selectedCheck.status !== 'draft'">作答 {{ selectedCheck.response_count }}/{{ selectedCheck.target_count }} · 正确 {{ selectedCheck.correct_count }}</p>
            <button v-if="selectedCheck.status === 'draft'" :disabled="checkBusy" @click="publishCheck">审核通过并定向发布</button>
            <button v-else-if="selectedCheck.status === 'active'" :disabled="checkBusy" @click="finishCheck">结束检测</button>
          </template>
          <button v-else-if="selected.status === 'awaiting_feedback'" :disabled="checkBusy" @click="createCheck">生成检测草稿</button>
          <p v-else-if="!selectedCheck" class="mode-note">结束本轮讲解并进入反馈阶段后，可生成一道检测题。</p>
        </section>
      </aside>
    </div>
    <section v-if="snapshot?.status !== 'ended' && snapshot?.pending_questions.length" class="surface pending-panel">
      <div class="pending-heading"><div><p class="eyebrow">RETRY QUEUE</p><h2>待处理问题</h2></div><button @click="retryAll">全部重试</button></div>
      <div v-for="item in snapshot.pending_questions" :key="item.id" class="pending-row"><span>{{ item.content }}</span><button @click="retry(item.id)">重新处理</button></div>
    </section>
  </main>
</template>
