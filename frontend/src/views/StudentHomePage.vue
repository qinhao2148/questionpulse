<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { joinClassroomByCode, listStudentClassrooms } from '../services/api'

const router = useRouter()
const joinCode = ref('')
const displayName = ref(localStorage.getItem('questionpulse.student_display_name') || '')
const error = ref('')
const joining = ref(false)
const classrooms = listStudentClassrooms()

async function enterClassroom() {
  error.value = ''
  joining.value = true
  try {
    let viewerKey = localStorage.getItem('questionpulse.viewer_key')
    if (!viewerKey) { viewerKey = crypto.randomUUID(); localStorage.setItem('questionpulse.viewer_key', viewerKey) }
    const name = displayName.value.trim()
    localStorage.setItem('questionpulse.student_display_name', name)
    const classroom = await joinClassroomByCode(joinCode.value.trim().toUpperCase(), name, viewerKey)
    await router.push(`/student/${classroom.session_id}`)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '加入课堂失败'
  } finally {
    joining.value = false
  }
}
</script>

<template>
  <main class="workspace classroom-center">
    <header class="center-heading"><div><p class="eyebrow">学生课堂</p><h1>我的课堂</h1><p>输入教师提供的课堂码和访问名称，进入正在进行的课堂。</p></div></header>
    <section class="surface student-entry-card">
      <div><h2>加入课堂</h2><p>访问名称只用于保存和识别你自己的课堂记录。</p></div>
      <form class="student-entry-form" @submit.prevent="enterClassroom">
        <label><span>课堂码</span><input v-model="joinCode" maxlength="12" autocomplete="off" placeholder="请输入课堂码" /></label>
        <label><span>访问名称</span><input v-model="displayName" maxlength="100" autocomplete="name" placeholder="例如：小明" /></label>
        <button class="primary-action" :disabled="joining || joinCode.trim().length < 4 || !displayName.trim()">{{ joining ? '正在进入…' : '进入课堂' }}</button>
        <p v-if="error" class="error-note">{{ error }}</p>
      </form>
    </section>
    <section class="classroom-section"><div class="section-title"><div><p class="eyebrow">最近参加</p><h2>课堂记录</h2></div><span>{{ classrooms.length }} 堂</span></div><div class="classroom-cards"><article v-for="item in classrooms" :key="item.id" class="surface classroom-card"><h3>{{ item.title }}</h3><p>最近进入 {{ new Date(item.updated_at).toLocaleString('zh-CN') }}</p><RouterLink class="button-link" :to="`/student/${item.id}`">进入课堂或查看回顾</RouterLink></article><p v-if="!classrooms.length" class="empty-state">参加课堂后，记录会显示在这里。</p></div></section>
    <p class="local-record-note">这里只显示你在当前浏览器参加过的课堂，不会展示其他学生的信息。</p>
  </main>
</template>
