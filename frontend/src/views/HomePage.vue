<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { createClassroom, fetchHealth } from '../services/api'

const router = useRouter()
const state = ref<'checking' | 'online' | 'offline'>('checking')
const detail = ref('正在检查 FastAPI 服务…')
const creating = ref(false)
const classroomTitle = ref('QuestionPulse 演示课堂')

async function startClassroom() {
  creating.value = true
  try {
    const classroom = await createClassroom(classroomTitle.value.trim() || 'QuestionPulse 课堂')
    await router.push(`/teacher/${classroom.id}`)
  } finally {
    creating.value = false
  }
}

onMounted(async () => {
  try {
    const result = await fetchHealth()
    state.value = 'online'
    detail.value = `${result.service} · ${result.environment}`
  } catch (error) {
    state.value = 'offline'
    detail.value = error instanceof Error ? error.message : '无法连接后端'
  }
})
</script>

<template>
  <main class="hero">
    <section>
      <p class="eyebrow">POLYV HACKATHON 2026</p>
      <h1>让课堂里的每一个疑问<br />都被看见和解决。</h1>
      <p class="intro">QuestionPulse 将零散提问聚合成教师可处理的群体疑问，并追踪讲解后的理解反馈。</p>
      <div class="status-card" :data-state="state">
        <span class="status-dot" aria-hidden="true"></span>
        <div>
          <strong>{{ state === 'checking' ? '检查中' : state === 'online' ? '开发环境已连接' : '后端尚未启动' }}</strong>
          <p>{{ detail }}</p>
        </div>
      </div>
      <label class="classroom-title-field">
        <span>课堂名称</span>
        <input v-model="classroomTitle" maxlength="200" placeholder="例如：数据结构期中复习" />
      </label>
      <button class="start-button" :disabled="state !== 'online' || creating" @click="startClassroom">
        {{ creating ? '正在创建…' : '创建本地课堂' }}
      </button>
    </section>
    <aside class="panel">
      <p>当前里程碑</p>
      <h2>可评审原型</h2>
      <ol>
        <li class="done">Vue 3 + TypeScript</li>
        <li class="done">FastAPI + Pydantic</li>
        <li class="done">MySQL + Alembic</li>
        <li class="done">三端产品线框</li>
        <li class="done">POLYV 真实直播与问答接入</li>
      </ol>
    </aside>
  </main>
</template>

