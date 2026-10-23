<template>
  <aside
    v-if="enabled"
    class="questionpulse-panel"
    :class="{ 'is-collapsed': collapsed, 'is-join-mode': joinMode }"
  >
    <header
      class="questionpulse-panel__header"
      @click="toggleCollapsed"
    >
      <div>
        <strong>QuestionPulse</strong><span>{{ connectionLabel }}</span>
      </div>
      <button type="button">
        {{ collapsed ? '展开' : '收起' }}
      </button>
    </header>
    <div
      v-if="!collapsed"
      class="questionpulse-panel__body"
    >
      <form
        v-if="joinMode"
        class="questionpulse-join"
        @submit.prevent="joinClassroom"
      >
        <h3>加入直播课堂</h3>
        <p>输入教师提供的课堂码，进入保利威直播和课堂互动。</p>
        <p
          v-if="duplicateTabHint"
          class="questionpulse-panel__error"
        >
          这个标签页复制了自己已经进入的课堂，保利威同一观众只能开一个播放器。请换一个名字重新进入，或关掉另一个标签页。
        </p>
        <input
          v-model="displayName"
          maxlength="100"
          placeholder="你的姓名"
        />
        <input
          v-model="joinCode"
          maxlength="12"
          placeholder="课堂码"
        />
        <button
          type="submit"
          :disabled="joining || !displayName.trim() || joinCode.trim().length < 4"
        >
          {{ joining ? '正在进入…' : '进入课堂' }}
        </button>
      </form>
      <p
        v-if="error"
        class="questionpulse-panel__error"
      >
        {{ error }}
      </p>
      <template v-if="snapshot">
        <section
          v-for="cluster in activeClusters"
          :key="cluster.id"
          class="questionpulse-card"
        >
          <small>{{ cluster.status === 'addressing' ? '教师正在讲解' : '讲解已结束' }}</small>
          <h3>{{ cluster.title }}</h3>
          <div
            v-if="cluster.status === 'awaiting_feedback' && !cluster.feedback.my_result"
            class="questionpulse-actions"
          >
            <button
              type="button"
              @click="submitFeedback(cluster, 'understood')"
            >
              已经理解
            </button>
            <button
              type="button"
              class="secondary"
              @click="submitFeedback(cluster, 'still_confused')"
            >
              仍然困惑
            </button>
          </div>
          <p
            v-else-if="cluster.feedback.my_result"
            class="questionpulse-success"
          >
            已反馈：{{ cluster.feedback.my_result === 'understood' ? '已经理解' : '仍然困惑' }}
          </p>
          <p
            v-else
            class="questionpulse-note"
          >
            听老师讲完后，这里会出现「已经理解 / 仍然困惑」两个按钮。
          </p>
        </section>

        <section
          v-for="check in checks"
          :key="check.id"
          class="questionpulse-card"
        >
          <small>理解检测</small>
          <h3>{{ check.stem }}</h3>
          <button
            v-for="option in check.options"
            :key="option.key"
            type="button"
            class="questionpulse-option"
            :class="{ selected: check.my_option_key === option.key }"
            :disabled="Boolean(check.my_option_key)"
            @click="submitAnswer(check.id, option.key)"
          >
            {{ option.key }}. {{ option.content }}
          </button>
          <p
            v-if="check.my_option_key"
            class="questionpulse-success"
            :class="{ 'is-wrong': check.my_is_correct === false }"
          >
            已提交 {{ check.my_option_key }} ·
            {{ check.my_is_correct ? '回答正确' : '回答错误' }}
            <template v-if="check.correct_option_key">
              ，正确答案 {{ check.correct_option_key }}
            </template>
          </p>
          <p
            v-if="check.my_option_key && check.explanation"
            class="questionpulse-note"
          >
            {{ check.explanation }}
          </p>
        </section>

        <p
          v-if="!activeClusters.length && !checks.length"
          class="questionpulse-empty"
        >
          聊天中的课程疑问会自动识别并汇总给教师。
        </p>

        <button
          v-if="!joinMode"
          type="button"
          class="questionpulse-switch"
          @click="switchClassroom"
        >
          退出课堂 / 换一个课堂码
        </button>
      </template>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { ChatEvents, ChatMsgSource, ChatMsgType } from '@polyv/live-watch-sdk';
import { useGlobalInject } from '@/app/use-global-inject';
import {
  answerQuestionPulseCheck,
  clearQuestionPulseCredentials,
  fetchQuestionPulseChecks,
  fetchQuestionPulseSnapshot,
  joinQuestionPulseClassroom,
  QuestionPulseApiError,
  questionPulseCredentials,
  questionPulseJoinUrl,
  sendQuestionPulseFeedback,
  uploadQuestionPulseChat,
  type QuestionPulseCheck,
  type QuestionPulseCluster,
  type QuestionPulseSnapshot,
} from './api';

// ?qpJoin=1 forces the join screen. The launcher and the docs hand out that link,
// and it used to be decorative: the only real trigger was "no cached identity".
const forcedJoin = new URLSearchParams(window.location.search).get('qpJoin') === '1';
// tab-guard 发现同一个学生已经在别的标签页里播放，会把本页踢回加入表单。
const duplicateTabHint = new URLSearchParams(window.location.search).get('qpDup') === '1';
const joinMode = forcedJoin || !questionPulseCredentials;
const enabled = true;
const collapsed = ref(false);
// Never pre-fill this field. It used to read the last name saved on this
// machine, so a student who typed nothing entered the lesson under whoever had
// used the browser before them.
const displayName = ref('');
const joinCode = ref('');
const joining = ref(false);
const snapshot = ref<QuestionPulseSnapshot | null>(null);
const checks = ref<QuestionPulseCheck[]>([]);
const error = ref('');
const uploaded = new Set<string>();
let refreshTimer: number | undefined;
const { getWatchCore } = useGlobalInject();

// A teacher can run several clusters at once (start explaining A, then B), so
// every active cluster is shown instead of only the first one found.
const activeClusters = computed<QuestionPulseCluster[]>(() =>
  (snapshot.value?.clusters || []).filter(cluster =>
    ['addressing', 'awaiting_feedback'].includes(cluster.status),
  ),
);
const connectionLabel = computed(() => {
  if (joinMode) return '学生入口';
  if (snapshot.value?.status === 'ended') return '课堂已结束';
  if (error.value) return '连接异常';
  return snapshot.value?.title ? `当前课堂：${snapshot.value.title}` : '疑问识别已连接';
});

function toggleCollapsed() {
  // In join mode the header is the top bar of a full-screen form. Collapsing it
  // used to hide the only way into the classroom with no visible way back.
  if (joinMode) return;
  collapsed.value = !collapsed.value;
}

async function joinClassroom() {
  joining.value = true;
  error.value = '';
  try {
    await joinQuestionPulseClassroom(joinCode.value, displayName.value);
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '加入课堂失败';
    joining.value = false;
  }
}

/** A stale or missing identity must lead somewhere, not into a dead end. */
let leaving = false;

function leaveClassroom(message: string) {
  // The 3s poll can fire again before the navigation lands; without this guard
  // the student would get the same alert twice.
  if (leaving) return;
  leaving = true;
  clearQuestionPulseCredentials();
  window.alert(message);
  window.location.assign(questionPulseJoinUrl());
}

function handleError(reason: unknown) {
  if (
    reason instanceof QuestionPulseApiError &&
    ['access_denied', 'access_expired', 'participant_not_in_session', 'no_credentials'].includes(
      reason.code,
    )
  ) {
    leaveClassroom('课堂身份已失效，请重新输入课堂码。');
    return;
  }
  error.value = reason instanceof Error ? reason.message : '操作失败，请稍后重试';
}

async function refresh() {
  if (!enabled) return;
  try {
    snapshot.value = await fetchQuestionPulseSnapshot();
    checks.value = snapshot.value.status === 'ended' ? [] : await fetchQuestionPulseChecks();
    error.value = '';
  } catch (reason) {
    handleError(reason);
  }
}

async function submitFeedback(cluster: QuestionPulseCluster, result: string) {
  error.value = '';
  try {
    await sendQuestionPulseFeedback(cluster.id, cluster.feedback_round, result);
    await refresh();
  } catch (reason) {
    handleError(reason);
  }
}

async function submitAnswer(checkId: string, optionKey: string) {
  error.value = '';
  try {
    await answerQuestionPulseCheck(checkId, optionKey);
    await refresh();
  } catch (reason) {
    handleError(reason);
  }
}

function switchClassroom() {
  if (!window.confirm('退出当前课堂并重新输入课堂码？')) return;
  clearQuestionPulseCredentials();
  window.location.assign(questionPulseJoinUrl());
}

function isOwnMessage(chatMsg: ChatMsgType) {
  const msg = chatMsg as ChatMsgType & {
    isSelf?: boolean;
    isLocal?: boolean;
    user?: { userId?: string };
  };
  // 公聊文本（ChatMsgSource.Speak）的类型定义里没有 isSelf，SDK 只对打赏/图片标记 isSelf。
  // 因此先看 isSelf/isLocal，再回退到「消息 userId 是否等于当前观众」。
  if (msg.isSelf === true || msg.isLocal === true) return true;
  const userId = msg.user?.userId;
  if (!userId) return false;
  try {
    return getWatchCore().user.isCurrentUser(userId);
  } catch {
    return false;
  }
}

function uploadIfConfirmed(chatMsg: ChatMsgType) {
  if (!enabled || chatMsg.msgSource !== ChatMsgSource.Speak) return;
  const speak = chatMsg as ChatMsgType & {
    content?: string;
    time?: number;
    isLocal?: boolean;
    isSended?: boolean;
    isSendFailed?: boolean;
  };
  if (!isOwnMessage(chatMsg) || speak.isSendFailed || !speak.content || uploaded.has(speak.id))
    return;
  if (speak.isLocal === true && speak.isSended !== true) return;
  uploaded.add(speak.id);
  uploadQuestionPulseChat({ id: speak.id, content: speak.content, time: speak.time }).catch(() => {
    uploaded.delete(speak.id);
  });
}

function onChatMessage(event: { chatMsg: ChatMsgType }) {
  uploadIfConfirmed(event.chatMsg);
}

function onReplaceChatMessage(event: { chatMsg: ChatMsgType }) {
  uploadIfConfirmed(event.chatMsg);
}

onMounted(() => {
  if (joinMode) return;
  const watchCore = getWatchCore();
  watchCore.chat.eventEmitter.on(ChatEvents.ChatMessage, onChatMessage);
  watchCore.chat.eventEmitter.on(ChatEvents.ReplaceChatMessage, onReplaceChatMessage);
  refresh().catch(() => undefined);
  refreshTimer = window.setInterval(refresh, 3000);
});

onBeforeUnmount(() => {
  window.clearInterval(refreshTimer);
  if (joinMode) return;
  const watchCore = getWatchCore();
  watchCore.chat.eventEmitter.off(ChatEvents.ChatMessage, onChatMessage);
  watchCore.chat.eventEmitter.off(ChatEvents.ReplaceChatMessage, onReplaceChatMessage);
});
</script>

<style lang="scss">
.questionpulse-panel {
  position: fixed;
  right: 18px;
  bottom: 18px;
  z-index: 10020;
  width: min(360px, calc(100vw - 24px));
  overflow: hidden;
  font-size: 14px;
  color: #172033;
  background: rgba(255, 255, 255, 0.97);
  border: 1px solid rgba(118, 139, 255, 0.35);
  border-radius: 18px;
  box-shadow: 0 18px 50px rgba(17, 27, 68, 0.24);
}
.questionpulse-panel.is-join-mode {
  inset: 0;
  display: grid;
  place-items: center;
  width: 100vw;
  background: #f4f6fb;
  border: 0;
  border-radius: 0;
}
.questionpulse-panel.is-join-mode .questionpulse-panel__header {
  position: absolute;
  top: 0;
  right: 0;
  left: 0;
}
.questionpulse-panel.is-join-mode .questionpulse-panel__header button {
  display: none;
}
.questionpulse-panel.is-join-mode .questionpulse-panel__body {
  width: min(420px, calc(100vw - 32px));
  padding: 26px;
  background: white;
  border-radius: 18px;
  box-shadow: 0 18px 50px rgba(17, 27, 68, 0.14);
}
.questionpulse-panel__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
  color: white;
  cursor: pointer;
  background: linear-gradient(135deg, #5367f8, #7655dc);
  div {
    display: grid;
    gap: 2px;
  }
  span {
    max-width: 240px;
    overflow: hidden;
    font-size: 11px;
    text-overflow: ellipsis;
    white-space: nowrap;
    opacity: 0.82;
  }
  button {
    color: white;
    cursor: pointer;
    background: transparent;
    border: 0;
  }
}
.questionpulse-panel__body {
  max-height: 55vh;
  padding: 12px;
  overflow: auto;
}
.questionpulse-join {
  display: grid;
  gap: 10px;
}
.questionpulse-join h3,
.questionpulse-join p {
  margin: 0;
}
.questionpulse-join p {
  line-height: 1.5;
  color: #687189;
}
.questionpulse-join input,
.questionpulse-join button {
  box-sizing: border-box;
  width: 100%;
  padding: 10px 12px;
  border: 1px solid #dfe3f7;
  border-radius: 9px;
}
.questionpulse-join button {
  color: white;
  cursor: pointer;
  background: #5667ed;
  border: 0;
}
.questionpulse-card {
  padding: 12px;
  margin-bottom: 10px;
  background: #f5f6ff;
  border-radius: 12px;
}
.questionpulse-card small {
  color: #6270d8;
}
.questionpulse-card h3 {
  margin: 5px 0 10px;
  font-size: 15px;
  line-height: 1.45;
}
.questionpulse-actions {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}
.questionpulse-actions button,
.questionpulse-option {
  padding: 9px 10px;
  color: white;
  cursor: pointer;
  background: #5667ed;
  border: 0;
  border-radius: 9px;
}
.questionpulse-actions .secondary {
  color: #4f5dbf;
  background: #e4e7ff;
}
.questionpulse-option {
  display: block;
  width: 100%;
  margin-top: 6px;
  color: #26325c;
  text-align: left;
  background: white;
  border: 1px solid #dfe3f7;
}
.questionpulse-option:disabled {
  cursor: default;
  opacity: 0.65;
}
.questionpulse-success {
  margin: 8px 0 0;
  color: #18845c;
}
.questionpulse-panel__error {
  color: #b43b45;
}
.questionpulse-empty {
  margin: 4px;
  line-height: 1.55;
  color: #687189;
}
.questionpulse-note {
  margin: 8px 0 0;
  font-size: 12px;
  line-height: 1.55;
  color: #687189;
}
.questionpulse-success.is-wrong {
  color: #b43b45;
}
.questionpulse-option.selected {
  background: #f0f2ff;
  border-color: #5667ed;
}
.questionpulse-switch {
  width: 100%;
  padding: 8px;
  margin-top: 6px;
  color: #687189;
  cursor: pointer;
  background: transparent;
  border: 1px dashed #d6daea;
  border-radius: 9px;
}
@media (max-width: 640px) {
  .questionpulse-panel {
    right: 12px;
    bottom: 72px;
  }
  .questionpulse-panel__body {
    max-height: 44vh;
  }
}
</style>
