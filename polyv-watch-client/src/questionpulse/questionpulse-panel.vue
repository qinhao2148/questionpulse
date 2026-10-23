<template>
  <aside
    v-if="enabled"
    class="questionpulse-panel"
    :class="{ 'is-collapsed': collapsed }"
  >
    <header
      class="questionpulse-panel__header"
      @click="collapsed = !collapsed"
    >
      <div>
        <strong>QuestionPulse</strong><span>{{ connectionLabel }}</span>
      </div>
      <button type="button">{{ collapsed ? '展开' : '收起' }}</button>
    </header>
    <div
      v-if="!collapsed"
      class="questionpulse-panel__body"
    >
      <p
        v-if="error"
        class="questionpulse-panel__error"
      >
        {{ error }}
      </p>
      <template v-if="snapshot">
        <section
          v-if="activeCluster"
          class="questionpulse-card"
        >
          <small>{{ activeCluster.status === 'addressing' ? '教师正在讲解' : '讲解已结束' }}</small>
          <h3>{{ activeCluster.title }}</h3>
          <div
            v-if="activeCluster.status === 'awaiting_feedback' && !activeCluster.feedback.my_result"
            class="questionpulse-actions"
          >
            <button
              type="button"
              @click="submitFeedback('understood')"
            >
              已经理解
            </button>
            <button
              type="button"
              class="secondary"
              @click="submitFeedback('still_confused')"
            >
              仍然困惑
            </button>
          </div>
          <p
            v-else-if="activeCluster.feedback.my_result"
            class="questionpulse-success"
          >
            已反馈：{{
              activeCluster.feedback.my_result === 'understood' ? '已经理解' : '仍然困惑'
            }}
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
            :disabled="Boolean(check.my_option_key)"
            @click="submitAnswer(check.id, option.key)"
          >
            {{ option.key }}. {{ option.content }}
          </button>
          <p
            v-if="check.my_option_key"
            class="questionpulse-success"
          >
            已提交答案 {{ check.my_option_key }}
          </p>
        </section>

        <p
          v-if="!activeCluster && !checks.length"
          class="questionpulse-empty"
        >
          聊天中的课程疑问会自动识别并汇总给教师。
        </p>
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
  fetchQuestionPulseChecks,
  fetchQuestionPulseSnapshot,
  questionPulseCredentials,
  sendQuestionPulseFeedback,
  uploadQuestionPulseChat,
  type QuestionPulseCheck,
  type QuestionPulseSnapshot,
} from './api';

const enabled = Boolean(questionPulseCredentials);
const collapsed = ref(false);
const snapshot = ref<QuestionPulseSnapshot | null>(null);
const checks = ref<QuestionPulseCheck[]>([]);
const error = ref('');
const uploaded = new Set<string>();
let refreshTimer: number | undefined;
const { getWatchCore } = useGlobalInject();

const activeCluster = computed(() =>
  snapshot.value?.clusters.find(cluster =>
    ['addressing', 'awaiting_feedback'].includes(cluster.status),
  ),
);
const connectionLabel = computed(() => {
  if (snapshot.value?.status === 'ended') return '课堂已结束';
  if (error.value) return '连接异常';
  return '疑问识别已连接';
});

async function refresh() {
  if (!enabled) return;
  try {
    snapshot.value = await fetchQuestionPulseSnapshot();
    checks.value = snapshot.value.status === 'ended' ? [] : await fetchQuestionPulseChecks();
    error.value = '';
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '暂时无法同步课堂状态';
  }
}

async function submitFeedback(result: string) {
  if (!activeCluster.value) return;
  await sendQuestionPulseFeedback(
    activeCluster.value.id,
    activeCluster.value.feedback_round,
    result,
  );
  await refresh();
}

async function submitAnswer(checkId: string, optionKey: string) {
  await answerQuestionPulseCheck(checkId, optionKey);
  await refresh();
}

function uploadIfConfirmed(chatMsg: ChatMsgType) {
  if (!enabled || chatMsg.msgSource !== ChatMsgSource.Speak) return;
  const speak = chatMsg as ChatMsgType & {
    content?: string;
    time?: number;
    isSelf?: boolean;
    isLocal?: boolean;
    isSended?: boolean;
    isSendFailed?: boolean;
  };
  if (!speak.isSelf || speak.isSendFailed || !speak.content || uploaded.has(speak.id)) return;
  if (speak.isLocal && !speak.isSended) return;
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
  if (!enabled) return;
  const watchCore = getWatchCore();
  watchCore.chat.eventEmitter.on(ChatEvents.ChatMessage, onChatMessage);
  watchCore.chat.eventEmitter.on(ChatEvents.ReplaceChatMessage, onReplaceChatMessage);
  refresh().catch(() => undefined);
  refreshTimer = window.setInterval(refresh, 3000);
});

onBeforeUnmount(() => {
  window.clearInterval(refreshTimer);
  if (!enabled) return;
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
    font-size: 11px;
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
