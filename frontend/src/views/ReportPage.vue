<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import { fetchReport, type SessionReport } from '../services/api'

const route = useRoute()
const report = ref<SessionReport | null>(null)
const error = ref('')
const loading = ref(true)
const statusLabel: Record<string, string> = {
  open: '待处理', addressing: '讲解中', awaiting_feedback: '等待反馈', closed: '已完成',
}
const coverage = computed(() => Math.round((report.value?.feedback_coverage || 0) * 100))
const checkAccuracy = computed(() => Math.round((report.value?.check_accuracy || 0) * 100))

async function loadReport() {
  error.value = ''
  try {
    report.value = await fetchReport(String(route.params.sessionId))
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '报告加载失败'
  } finally {
    loading.value = false
  }
}

function printReport() {
  window.print()
}

function exportCsv() {
  if (!report.value) return
  const escape = (value: string | number) => `"${String(value).replaceAll('"', '""')}"`
  const rows = [['疑问主题', '状态', '影响人数', '问题数', '已理解', '仍困惑']]
  report.value.clusters.forEach((cluster) => rows.push([
    cluster.title, cluster.status, String(cluster.participant_count), String(cluster.question_count),
    String(cluster.feedback.understood), String(cluster.feedback.still_confused),
  ]))
  const csv = `\uFEFF${rows.map((row) => row.map(escape).join(',')).join('\n')}`
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = `questionpulse-${report.value.id}.csv`
  link.click()
  URL.revokeObjectURL(url)
}

onMounted(loadReport)
</script>

<template>
  <main class="workspace report-page">
    <p v-if="error" class="error-note">{{ error }}</p>
    <section v-if="loading" class="surface page-state"><p class="eyebrow">课堂报告</p><h1>正在生成报告…</h1><p>正在汇总课堂问题与反馈。</p></section>
    <section v-else-if="!report" class="surface page-state"><p class="eyebrow">课堂报告</p><h1>暂时无法查看报告</h1><p>{{ error || '请稍后重试。' }}</p><button @click="loadReport">重新加载</button></section>
    <template v-if="report">
      <header class="page-heading">
        <div><p class="eyebrow">课堂报告</p><h1>{{ report.title }}</h1><p>{{ report.status === 'ended' ? `课堂已结束 · ${report.ended_at ? new Date(report.ended_at).toLocaleString('zh-CN') : ''}` : '课堂进行中' }} · 更新于 {{ new Date(report.generated_at).toLocaleString('zh-CN') }}</p></div>
        <div class="report-actions"><button @click="loadReport">刷新</button><button @click="exportCsv">导出 CSV</button><button class="print-button" @click="printReport">打印报告</button></div>
      </header>
      <section class="report-hero surface">
        <div><span>问题总数</span><strong>{{ report.question_count }}</strong></div>
        <div><span>提问学生</span><strong>{{ report.participant_count }}</strong></div>
        <div><span>疑问主题</span><strong>{{ report.cluster_count }}</strong></div>
        <div><span>反馈覆盖率</span><strong>{{ coverage }}%</strong></div>
        <div><span>检测正确率</span><strong>{{ checkAccuracy }}%</strong></div>
      </section>
      <section class="report-grid">
        <article class="surface report-section">
          <p class="eyebrow">重点问题</p><h2>高频疑问</h2>
          <div v-for="(cluster, index) in report.clusters" :key="cluster.id" class="rank-row">
            <b>{{ String(index + 1).padStart(2, '0') }}</b>
            <div><strong>{{ cluster.title }}</strong><span>{{ cluster.participant_count }} 人 · {{ cluster.question_count }} 条问题 · {{ statusLabel[cluster.status] || '处理中' }}</span>
              <div v-if="cluster.feedback_history?.length" class="round-history">
                <span v-for="round in cluster.feedback_history" :key="round.round">第 {{ round.round }} 轮：{{ round.responses }}/{{ round.targets }} 已反馈，{{ round.still_confused }} 人仍困惑</span>
              </div>
              <details><summary>查看原始问题</summary><p v-for="question in cluster.questions" :key="question.id">{{ question.content }}</p></details>
            </div>
          </div>
          <p v-if="!report.clusters.length" class="empty-state">本课堂还没有问题。</p>
        </article>
        <article class="surface report-section">
          <p class="eyebrow">学习反馈</p><h2>理解情况</h2>
          <div class="donut" :style="{ background: `conic-gradient(#73dfaf 0 ${report.feedback_responses ? report.understood / report.feedback_responses * 100 : 0}%, #f3a85f 0)` }"><div><strong>{{ report.feedback_responses }}</strong><span>已反馈</span></div></div>
          <div class="legend"><span><i class="good"></i>已理解 {{ report.understood }}</span><span><i class="warn"></i>仍困惑 {{ report.still_confused }}</span></div>
          <div class="assessment-summary"><strong>{{ report.check_correct }}/{{ report.check_responses }}</strong><span>已作答中答对 · 共发放 {{ report.check_targets }} 人次</span></div>
          <h3>仍需跟进</h3>
          <p v-for="cluster in report.follow_ups" :key="cluster.id" class="follow-up">“{{ cluster.title }}”仍有 {{ cluster.feedback.still_confused }} 名学生困惑。</p>
          <p v-if="!report.follow_ups.length" class="follow-up">当前没有“仍困惑”反馈。</p>
        </article>
      </section>
      <section class="surface report-section ai-insight-section">
        <p class="eyebrow">智能分析</p><h2>教学建议</h2>
        <p class="evidence-note">建议由课堂问题分析生成；人数、反馈和检测结果以课堂记录为准。</p>
        <article v-for="insight in report.ai_insights" :key="insight.cluster_id" class="ai-insight-card">
          <div><strong>{{ insight.cluster_title }}</strong><span>基于课堂问题</span></div>
          <p><b>核心意图：</b>{{ insight.normalized_intent }}</p>
          <p><b>语义依据：</b>{{ insight.semantic_reason }}</p>
          <p><b>建议动作：</b>{{ insight.recommendation }}</p>
        </article>
        <p v-if="!report.ai_insights.length" class="empty-state">当前还没有可用的智能分析建议。</p>
      </section>
      <section class="surface report-section timeline-section">
        <p class="eyebrow">课堂过程</p><h2>疑问处理时间线</h2>
        <div v-for="(event, index) in report.timeline" :key="`${event.occurred_at}-${index}`" class="timeline-row">
          <time>{{ new Date(event.occurred_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) }}</time>
          <i></i>
          <div><strong>{{ event.detail }}</strong><span v-if="event.cluster_title">{{ event.cluster_title }}</span></div>
        </div>
        <p v-if="!report.timeline.length" class="empty-state">本课堂尚无处理事件。</p>
      </section>
      <p class="evidence-note">统计直接来自问题、独立参与者、反馈目标与理解检测；每个结论均可追溯到原始问题和课堂操作。</p>
    </template>
  </main>
</template>
