<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { createClassroom, fetchHealth, fetchTeacherClassrooms, getTeacherPortalToken, loginTeacher, logoutTeacher, type TeacherClassroomSummary } from '../services/api'

const router = useRouter()
const state = ref<'checking' | 'online' | 'offline'>('checking')
const loggedIn = ref(Boolean(getTeacherPortalToken()))
const username = ref('')
const password = ref('')
const loginBusy = ref(false)
const loginError = ref('')
const creating = ref(false)
const classroomTitle = ref('')
const createError = ref('')
const classrooms = ref<TeacherClassroomSummary[]>([])
const showAllHistory = ref(false)
const currentClassrooms = computed(() => classrooms.value.filter((item) => item.status !== 'ended'))
const endedClassrooms = computed(() => classrooms.value.filter((item) => item.status === 'ended'))
const visibleEndedClassrooms = computed(() =>
  showAllHistory.value ? endedClassrooms.value : endedClassrooms.value.slice(0, 6),
)

async function loadClassrooms() { classrooms.value = await fetchTeacherClassrooms() }
async function signIn() {
  loginError.value = ''; loginBusy.value = true
  try { await loginTeacher(username.value.trim(), password.value); loggedIn.value = true; password.value = ''; await loadClassrooms() }
  catch (error) { loginError.value = error instanceof Error ? error.message : '登录失败，请检查账号和密码' }
  finally { loginBusy.value = false }
}
function signOut() { logoutTeacher(); loggedIn.value = false; classrooms.value = [] }
async function startClassroom() {
  createError.value = ''; creating.value = true
  try { const classroom = await createClassroom(classroomTitle.value.trim()); await router.push(`/teacher/${classroom.id}`) }
  catch (error) { createError.value = error instanceof Error ? error.message : '课堂创建失败，请稍后重试' }
  finally { creating.value = false }
}
onMounted(async () => {
  window.addEventListener('questionpulse:teacher-login-required', signOut)
  try { await fetchHealth(); state.value = 'online' } catch { state.value = 'offline' }
  // A backend restart or a network blip must not throw away a valid login.
  // The request layer already signs out when the token itself is rejected.
  if (loggedIn.value) {
    try { await loadClassrooms() } catch (reason) {
      loginError.value = reason instanceof Error ? reason.message : '暂时无法读取课堂列表，请稍后重试'
    }
  }
})
onBeforeUnmount(() => window.removeEventListener('questionpulse:teacher-login-required', signOut))
</script>

<template>
  <main class="workspace classroom-center">
    <section v-if="!loggedIn" class="surface teacher-login-card">
      <div><p class="eyebrow">教师登录</p><h1>教师课堂中心</h1><p>登录后统一管理当前课堂、历史课堂和课堂报告。</p></div>
      <form class="teacher-login-form" @submit.prevent="signIn">
        <label><span>教师账号</span><input v-model="username" autocomplete="username" placeholder="请输入教师账号" /></label>
        <label><span>密码</span><input v-model="password" type="password" autocomplete="current-password" placeholder="请输入密码" /></label>
        <button class="primary-action" :disabled="loginBusy || !username.trim() || !password">{{ loginBusy ? '正在登录…' : '登录' }}</button>
        <p v-if="loginError" class="error-note">{{ loginError }}</p>
      </form>
    </section>

    <template v-else>
      <header class="center-heading"><div><p class="eyebrow">教师课堂中心</p><h1>我的课堂</h1><p>继续正在进行的课堂，或回顾已经结束的教学记录。</p></div><button @click="signOut">退出登录</button></header>
      <section class="surface create-classroom-card">
        <div><h2>创建新课堂</h2><p>课堂之间相互独立，历史问题和报告会继续保留。</p></div>
        <label class="classroom-title-field"><span>课堂名称</span><input v-model="classroomTitle" maxlength="200" placeholder="例如：数据结构期中复习" /></label>
        <button class="primary-action" :disabled="state !== 'online' || creating || !classroomTitle.trim()" @click="startClassroom">{{ creating ? '正在创建…' : '创建课堂' }}</button>
        <p v-if="createError" class="error-note">{{ createError }}</p>
      </section>
      <section class="classroom-section">
        <div class="section-title"><div><p class="eyebrow">进行中</p><h2>当前课堂</h2></div><span>{{ currentClassrooms.length }} 堂</span></div>
        <div class="classroom-cards">
          <article v-for="item in currentClassrooms" :key="item.id" class="surface classroom-card"><span class="status addressing">进行中</span><h3>{{ item.title }}</h3><p>课堂码 {{ item.join_code }} · {{ item.cluster_count }} 个疑问主题 · {{ item.question_count }} 条问题</p><div class="classroom-card-actions"><RouterLink class="button-link" :to="`/teacher/${item.id}`">继续课堂</RouterLink><RouterLink :to="`/report/${item.id}`">查看报告</RouterLink></div></article>
          <p v-if="!currentClassrooms.length" class="empty-state">当前没有进行中的课堂。</p>
        </div>
      </section>
      <section class="classroom-section">
        <div class="section-title"><div><p class="eyebrow">历史记录</p><h2>已结束课堂</h2></div><span>{{ endedClassrooms.length }} 堂</span></div>
        <div class="classroom-cards">
          <article v-for="item in visibleEndedClassrooms" :key="item.id" class="surface classroom-card"><span class="status closed">已结束</span><h3>{{ item.title }}</h3><p>{{ item.cluster_count }} 个疑问主题 · {{ item.question_count }} 条问题</p><div class="classroom-card-actions"><RouterLink class="button-link" :to="`/teacher/${item.id}`">查看课堂</RouterLink><RouterLink :to="`/report/${item.id}`">课堂报告</RouterLink></div></article>
          <p v-if="!endedClassrooms.length" class="empty-state">结束课堂后，记录会出现在这里。</p>
        </div>
        <button v-if="endedClassrooms.length > visibleEndedClassrooms.length" class="history-toggle" @click="showAllHistory = true">展开全部 {{ endedClassrooms.length }} 堂历史课堂</button>
        <button v-else-if="showAllHistory && endedClassrooms.length > 6" class="history-toggle" @click="showAllHistory = false">收起历史课堂</button>
      </section>
    </template>
  </main>
</template>
