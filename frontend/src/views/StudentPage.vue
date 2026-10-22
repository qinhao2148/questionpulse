<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import {
  answerCheck,
  fetchStudentChecks,
  fetchStudentSnapshot,
  joinClassroom,
  sendFeedback,
  submitQuestion,
  type Snapshot,
  type CheckQuestion,
} from '../services/api'
import {
  mountPolyvWatch,
  refreshPolyvWatch,
  sendPolyvQuestion,
  unmountPolyvWatch,
  type PolyvWatchStatus,
} from '../services/polyvWatch'

const route = useRoute()
const sessionId = computed(() => String(route.params.sessionId))
const snapshot = ref<Snapshot | null>(null)
const checks = ref<CheckQuestion[]>([])
const answeringCheck = ref('')
const participantId = ref('')
const connectionError = ref('')
const playerElement = ref<HTMLDivElement | null>(null)
const polyvStatus = ref<PolyvWatchStatus>('idle')
const polyvStatusDetail = ref('等待课堂绑定频道')
const playerStarted = ref(false)
const polyvConnected = ref(false)
let reconnectAttempts = 0
let reconnectTimer: number | undefined

const question = ref('')
const submitted = ref(false)
const sendingFeedback = ref(false)
const active = computed(() => snapshot.value?.clusters.find(
  (item) => item.questions.length > 0 && ['addressing', 'awaiting_feedback'].includes(item.status),
))
const sessionEnded = computed(() => snapshot.value?.status === 'ended')
const stageState = computed(() => sessionEnded.value
  ? 'ended'
  : playerStarted.value ? 'player' : 'placeholder')
let refreshTimer: number | undefined

async function refresh() {
  if (!participantId.value) return
  snapshot.value = await fetchStudentSnapshot(sessionId.value)
  checks.value = sessionEnded.value ? [] : await fetchStudentChecks(sessionId.value)
  await nextTick()
  if (sessionEnded.value) {
    stopPlayer('课堂已结束，直播画面已关闭')
    return
  }
  await ensurePolyvWatch()
}

function updatePolyvStatus(status: PolyvWatchStatus, detail: string) {
  polyvStatus.value = status
  polyvStatusDetail.value = detail
  if (status === 'degraded' && reconnectAttempts < 2 && !sessionEnded.value) {
    window.clearTimeout(reconnectTimer)
    reconnectTimer = window.setTimeout(() => retryPlayer(true), 4000)
  }
}

function stopPlayer(detail: string) {
  window.clearTimeout(reconnectTimer)
  if (playerStarted.value) unmountPolyvWatch()
  playerStarted.value = false
  polyvConnected.value = false
  polyvStatus.value = sessionEnded.value ? 'ended' : 'idle'
  polyvStatusDetail.value = detail
}

async function ensurePolyvWatch(force = false) {
  const channelId = snapshot.value?.polyv_channel_id || import.meta.env.VITE_POLYV_CHANNEL_ID
  if (sessionEnded.value || !channelId || !playerElement.value || (playerStarted.value && !force)) return
  if (force) unmountPolyvWatch()
  playerStarted.value = true
  polyvConnected.value = false
  polyvStatus.value = 'loading'
  polyvStatusDetail.value = `正在连接频道 ${channelId}`
  try {
    await mountPolyvWatch(
      playerElement.value,
      channelId,
      localStorage.getItem('questionpulse.viewer_key') || crypto.randomUUID(),
      { onStatus: updatePolyvStatus },
    )
    polyvConnected.value = true
  } catch (reason) {
    polyvStatus.value = 'degraded'
    polyvStatusDetail.value = reason instanceof Error ? reason.message : '官方 SDK 初始化失败'
    updatePolyvStatus('degraded', polyvStatusDetail.value)
  }
}

async function retryPlayer(automatic = false) {
  if (sessionEnded.value) return
  reconnectAttempts += 1
  connectionError.value = ''
  if (!automatic && refreshPolyvWatch()) {
    polyvStatus.value = 'loading'
    polyvStatusDetail.value = '正在重新获取直播流'
    return
  }
  await ensurePolyvWatch(true)
}

async function connect() {
  try {
    let viewerKey = localStorage.getItem('questionpulse.viewer_key')
    if (!viewerKey) {
      viewerKey = crypto.randomUUID()
      localStorage.setItem('questionpulse.viewer_key', viewerKey)
    }
    const joinCode = String(route.query.code || sessionStorage.getItem(`questionpulse.student_join_code.${sessionId.value}`) || '')
    if (joinCode) sessionStorage.setItem(`questionpulse.student_join_code.${sessionId.value}`, joinCode)
    participantId.value = (await joinClassroom(sessionId.value, viewerKey, joinCode)).participant_id
    await nextTick()
    await refresh()
    refreshTimer = window.setInterval(refresh, 3000)
  } catch (error) {
    connectionError.value = error instanceof Error ? error.message : '无法连接课堂'
  }
}

async function sendQuestion() {
  if (!question.value.trim()) return
  try {
    if (polyvConnected.value) {
      await sendPolyvQuestion(question.value.trim())
    } else {
      await submitQuestion(sessionId.value, participantId.value, question.value, crypto.randomUUID())
    }
    submitted.value = true
    question.value = ''
    await refresh()
  } catch (error) {
    connectionError.value = error instanceof Error ? error.message : '提交失败'
  }
}

async function respond(result: 'understood' | 'still_confused') {
  if (!active.value || !participantId.value) return
  sendingFeedback.value = true
  try {
    await sendFeedback(
      sessionId.value,
      active.value.id,
      participantId.value,
      active.value.feedback_round,
      result,
    )
    await refresh()
  } catch (error) {
    connectionError.value = error instanceof Error ? error.message : '反馈失败'
  } finally {
    sendingFeedback.value = false
  }
}

async function answer(check: CheckQuestion, optionKey: string) {
  answeringCheck.value = check.id
  try {
    await answerCheck(sessionId.value, check.id, participantId.value, optionKey)
    await refresh()
  } catch (error) {
    connectionError.value = error instanceof Error ? error.message : '提交检测答案失败'
  } finally {
    answeringCheck.value = ''
  }
}

onMounted(connect)
onUnmounted(() => {
  window.clearInterval(refreshTimer)
  window.clearTimeout(reconnectTimer)
  if (playerStarted.value) unmountPolyvWatch()
})
</script>

<template>
  <main class="workspace student-layout">
    <section class="watch-stage" :class="`is-${stageState}`">
      <div class="stage-badge" :class="{ ended: sessionEnded }"><span class="live-dot"></span> {{ sessionEnded ? '课堂已结束' : polyvStatus === 'playing' ? 'POLYV LIVE' : '课堂直播' }}</div>
      <template v-if="sessionEnded">
        <div class="stage-message"><p class="eyebrow">SESSION COMPLETE</p><h1>{{ snapshot?.title }}</h1><p>本课堂互动已结束，直播画面已关闭。课堂数据已归档。</p></div>
      </template>
      <template v-else>
        <div v-if="!playerStarted" class="stage-message"><p class="eyebrow">QUESTIONPULSE CLASSROOM</p><h1>{{ snapshot?.title || '课堂直播' }}</h1><p>{{ polyvStatusDetail }}</p></div>
        <div ref="playerElement" class="polyv-player"></div>
        <div v-if="playerStarted && polyvStatus !== 'playing'" class="player-state" :class="polyvStatus">
          <strong>{{ polyvStatusDetail }}</strong>
          <span v-if="polyvStatus === 'ready'">浏览器阻止自动播放时，请点击播放器中央的播放按钮。</span>
          <button v-if="polyvStatus === 'degraded'" @click="retryPlayer(false)">重新连接直播</button>
        </div>
      </template>
    </section>

    <aside class="side-column">
      <section class="surface ask-box">
        <p class="eyebrow">QUESTION INPUT</p>
        <h2>哪里还没听懂？</h2>
        <textarea v-model="question" :disabled="sessionEnded" maxlength="500" :placeholder="sessionEnded ? '课堂已结束，无法继续提问' : '输入你的问题，例如：没有结束条件时会发生什么？'" />
        <div class="input-footer"><span>{{ question.length }}/500</span><button :disabled="!participantId || snapshot?.status === 'ended'" @click="sendQuestion">{{ snapshot?.status === 'ended' ? '课堂已结束' : '提交疑问' }}</button></div>
        <p class="mode-note">{{ sessionEnded ? '课堂记录已归档' : snapshot?.integration_status === 'connected' ? 'POLYV 真实数据已连接' : snapshot?.integration_status === 'degraded' ? 'POLYV 暂时断开，问题将保存在本地' : '本地课堂模式' }}</p>
        <p v-if="submitted" class="success-note">已收到。{{ polyvConnected ? '问题已发送到 POLYV，等待教师端同步分析。' : '你的问题正在匹配相似疑问。' }}</p>
        <p v-if="connectionError" class="error-note">{{ connectionError }}</p>
      </section>

      <section v-if="active" class="surface pulse-card active-pulse">
        <div class="card-row"><span class="status" :class="active.status">{{ active.status === 'addressing' ? '讲解中' : '等待反馈' }}</span><span>{{ active.participant_count }} 人同问</span></div>
        <h3>{{ active.title }}</h3>
        <p>{{ active.status === 'addressing' ? '教师正在讲解这个问题，结束后请反馈你是否理解。' : '本轮讲解已结束，请提交真实理解情况。' }}</p>
        <div v-if="active.status === 'awaiting_feedback'" class="feedback-row">
          <button :disabled="sendingFeedback" :class="{ selected: active.feedback.my_result === 'understood' }" @click="respond('understood')">✓ 已理解</button>
          <button :disabled="sendingFeedback" :class="{ selected: active.feedback.my_result === 'still_confused' }" @click="respond('still_confused')">? 仍困惑</button>
        </div>
        <p v-if="active.feedback.my_result" class="success-note">反馈已保存，可在本轮结束前修改。</p>
      </section>
      <section v-for="check in checks" :key="check.id" class="surface pulse-card check-card">
        <div class="card-row"><span class="status awaiting_feedback">理解检测</span><span>{{ check.response_count }}/{{ check.target_count }} 已答</span></div>
        <h3>{{ check.stem }}</h3>
        <div class="check-options">
          <button v-for="option in check.options" :key="option.key" :disabled="answeringCheck === check.id || check.my_option_key !== null" :class="{ selected: check.my_option_key === option.key }" @click="answer(check, option.key)"><strong>{{ option.key }}</strong>{{ option.content }}</button>
        </div>
        <p v-if="check.my_is_correct !== null" :class="check.my_is_correct ? 'success-note' : 'error-note'">{{ check.my_is_correct ? '回答正确，已经掌握。' : `暂未掌握，正确答案是 ${check.correct_option_key}。` }} {{ check.explanation }}</p>
      </section>
      <section v-if="!active" class="surface pulse-card"><h3>{{ sessionEnded ? '课堂已结束' : '等待教师讲解' }}</h3><p>{{ sessionEnded ? '课堂记录已冻结。教师可选择稍后发布脱敏课堂总结。' : '与你有关的课堂疑问会显示在这里。' }}</p></section>
    </aside>
  </main>
</template>
