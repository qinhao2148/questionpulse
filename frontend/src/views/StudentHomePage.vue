<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { listStudentClassrooms } from '../services/api'
const router = useRouter()
const classroomLink = ref('')
const error = ref('')
const classrooms = listStudentClassrooms()
async function enterClassroom() {
  error.value = ''
  try {
    const url = new URL(classroomLink.value.trim(), window.location.origin)
    if (!/^\/student\/[^/]+$/.test(url.pathname)) throw new Error('请粘贴教师分享的完整学生课堂链接')
    await router.push(`${url.pathname}${url.search}`)
  } catch (reason) { error.value = reason instanceof Error ? reason.message : '课堂链接不正确' }
}
</script>
<template>
  <main class="workspace classroom-center">
    <header class="center-heading"><div><p class="eyebrow">学生课堂</p><h1>我的课堂</h1><p>加入正在进行的课堂，或查看自己的课堂记录。</p></div></header>
    <section class="surface join-classroom-card"><div><h2>加入课堂</h2><p>粘贴教师分享的学生课堂链接。</p></div><input v-model="classroomLink" placeholder="http://127.0.0.1:5173/student/…?code=…" @keyup.enter="enterClassroom" /><button class="primary-action" :disabled="!classroomLink.trim()" @click="enterClassroom">进入课堂</button><p v-if="error" class="error-note">{{ error }}</p></section>
    <section class="classroom-section"><div class="section-title"><div><p class="eyebrow">最近参加</p><h2>课堂记录</h2></div><span>{{ classrooms.length }} 堂</span></div><div class="classroom-cards"><article v-for="item in classrooms" :key="item.id" class="surface classroom-card"><h3>{{ item.title }}</h3><p>最近进入 {{ new Date(item.updated_at).toLocaleString('zh-CN') }}</p><RouterLink class="button-link" :to="`/student/${item.id}${item.join_code ? `?code=${item.join_code}` : ''}`">进入课堂或查看回顾</RouterLink></article><p v-if="!classrooms.length" class="empty-state">参加课堂后，记录会显示在这里。</p></div></section>
    <p class="local-record-note">这里只显示你在当前浏览器参加过的课堂，不会展示其他学生的信息。</p>
  </main>
</template>
