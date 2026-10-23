<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { createClassroom, fetchHealth, fetchTeacherSnapshot, listTeacherClassrooms, type LocalClassroomRecord, type Snapshot } from '../services/api'

type ClassroomItem = LocalClassroomRecord & { snapshot?: Snapshot; unavailable?: boolean }
const router = useRouter()
const state = ref<'checking' | 'online' | 'offline'>('checking')
const creating = ref(false)
const classroomTitle = ref('')
const createError = ref('')
const classrooms = ref<ClassroomItem[]>([])

async function loadClassrooms() {
  classrooms.value = await Promise.all(listTeacherClassrooms().map(async (record) => {
    try { return { ...record, snapshot: await fetchTeacherSnapshot(record.id) } }
    catch { return { ...record, unavailable: true } }
  }))
}
async function startClassroom() {
  createError.value = ''; creating.value = true
  try { const classroom = await createClassroom(classroomTitle.value.trim()); await router.push(`/teacher/${classroom.id}`) }
  catch (error) { createError.value = error instanceof Error ? error.message : '课堂创建失败，请稍后重试' }
  finally { creating.value = false }
}
onMounted(async () => {
  try { await fetchHealth(); state.value = 'online' } catch { state.value = 'offline' }
  await loadClassrooms()
})
</script>

<template>
  <main class="workspace classroom-center">
    <header class="center-heading"><div><p class="eyebrow">教师课堂中心</p><h1>我的课堂</h1><p>继续正在进行的课堂，或回顾已经结束的教学记录。</p></div><RouterLink class="button-link" to="/student">切换到学生入口</RouterLink></header>
    <section class="surface create-classroom-card">
      <div><h2>创建新课堂</h2><p>课堂之间相互独立，历史问题和报告会继续保留。</p></div>
      <label class="classroom-title-field"><span>课堂名称</span><input v-model="classroomTitle" maxlength="200" placeholder="例如：数据结构期中复习" /></label>
      <button class="primary-action" :disabled="state !== 'online' || creating || !classroomTitle.trim()" @click="startClassroom">{{ creating ? '正在创建…' : '创建课堂' }}</button>
      <p v-if="createError" class="error-note">{{ createError }}</p>
    </section>
    <section class="classroom-section">
      <div class="section-title"><div><p class="eyebrow">进行中</p><h2>当前课堂</h2></div><span>{{ classrooms.filter((item) => item.snapshot?.status !== 'ended' && !item.unavailable).length }} 堂</span></div>
      <div class="classroom-cards">
        <article v-for="item in classrooms.filter((record) => record.snapshot?.status !== 'ended' && !record.unavailable)" :key="item.id" class="surface classroom-card">
          <span class="status addressing">进行中</span><h3>{{ item.snapshot?.title || item.title }}</h3><p>{{ item.snapshot?.clusters.length || 0 }} 个疑问主题 · {{ item.snapshot?.clusters.reduce((sum, cluster) => sum + cluster.question_count, 0) || 0 }} 条问题</p>
          <div class="classroom-card-actions"><RouterLink class="button-link" :to="`/teacher/${item.id}`">继续课堂</RouterLink><RouterLink :to="`/report/${item.id}`">查看报告</RouterLink></div>
        </article>
        <p v-if="!classrooms.some((item) => item.snapshot?.status !== 'ended' && !item.unavailable)" class="empty-state">当前没有进行中的课堂。</p>
      </div>
    </section>
    <section class="classroom-section">
      <div class="section-title"><div><p class="eyebrow">历史记录</p><h2>已结束课堂</h2></div><span>{{ classrooms.filter((item) => item.snapshot?.status === 'ended').length }} 堂</span></div>
      <div class="classroom-cards">
        <article v-for="item in classrooms.filter((record) => record.snapshot?.status === 'ended')" :key="item.id" class="surface classroom-card">
          <span class="status closed">已结束</span><h3>{{ item.snapshot?.title || item.title }}</h3><p>{{ item.snapshot?.clusters.length || 0 }} 个疑问主题 · {{ item.snapshot?.clusters.reduce((sum, cluster) => sum + cluster.question_count, 0) || 0 }} 条问题</p>
          <div class="classroom-card-actions"><RouterLink class="button-link" :to="`/teacher/${item.id}`">查看课堂</RouterLink><RouterLink :to="`/report/${item.id}`">课堂报告</RouterLink></div>
        </article>
        <p v-if="!classrooms.some((item) => item.snapshot?.status === 'ended')" class="empty-state">结束课堂后，记录会出现在这里。</p>
      </div>
    </section>
    <p class="local-record-note">课堂入口仅保存在当前浏览器中；更换设备时需要重新使用教师专属入口。</p>
  </main>
</template>
