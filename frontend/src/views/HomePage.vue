<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { createClassroom, fetchHealth } from '../services/api'

const router = useRouter()
const state = ref<'checking' | 'online' | 'offline'>('checking')
const detail = ref('正在连接课堂服务…')
const creating = ref(false)
const classroomTitle = ref('')
const createError = ref('')

async function startClassroom() {
  createError.value = ''
  creating.value = true
  try {
    const classroom = await createClassroom(classroomTitle.value.trim() || '未命名课堂')
    await router.push(`/teacher/${classroom.id}`)
  } catch (error) {
    createError.value = error instanceof Error ? error.message : '课堂创建失败，请稍后重试'
  } finally {
    creating.value = false
  }
}

onMounted(async () => {
  try {
    await fetchHealth()
    state.value = 'online'
    detail.value = '课堂服务运行正常'
  } catch {
    state.value = 'offline'
    detail.value = '课堂服务暂时不可用，请稍后重试'
  }
})
</script>

<template>
  <main class="hero">
    <section>
      <p class="eyebrow">课堂疑问脉搏</p>
      <h1>让课堂里的每一个疑问<br />都被看见和解决。</h1>
      <p class="intro">QuestionPulse 将零散提问聚合成教师可处理的群体疑问，并追踪讲解后的理解反馈。</p>
      <div class="status-card" :data-state="state">
        <span class="status-dot" aria-hidden="true"></span>
        <div>
          <strong>{{ state === 'checking' ? '正在连接' : state === 'online' ? '服务已就绪' : '暂时无法连接' }}</strong>
          <p>{{ detail }}</p>
        </div>
      </div>
      <label class="classroom-title-field">
        <span>课堂名称</span>
        <input v-model="classroomTitle" maxlength="200" placeholder="例如：数据结构期中复习" />
      </label>
      <button class="start-button" :disabled="state !== 'online' || creating || !classroomTitle.trim()" @click="startClassroom">
        {{ creating ? '正在创建…' : '创建课堂' }}
      </button>
      <p class="entry-note">创建后会自动进入教师工作台；教师权限由专属入口自动保存，无需手动申请。</p>
      <p v-if="createError" class="error-note">{{ createError }}</p>
    </section>
    <aside class="panel">
      <p>使用流程</p>
      <h2>让疑问形成闭环</h2>
      <ol>
        <li class="done">创建课堂并分享学生入口</li>
        <li class="done">自动汇总相似问题</li>
        <li class="done">按影响人数安排讲解</li>
        <li class="done">收集理解反馈与检测结果</li>
        <li class="done">课后生成可追溯报告</li>
      </ol>
    </aside>
  </main>
</template>

