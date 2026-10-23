<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'

const route = useRoute()
const pageLabel = computed(() => route.path === '/student' || route.path.startsWith('/student/')
  ? '学生课堂'
  : route.path.startsWith('/teacher/')
    ? '教师工作台'
    : route.path.startsWith('/report/') ? '课堂报告' : '课堂疑问助手')
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <RouterLink class="brand" to="/">QuestionPulse</RouterLink>
      <span class="role-boundary">{{ pageLabel }}</span>
    </header>
    <RouterView />
  </div>
</template>

