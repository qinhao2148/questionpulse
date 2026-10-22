<script setup lang="ts">
import { RouterLink, RouterView } from 'vue-router'
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <RouterLink class="brand" to="/">QuestionPulse</RouterLink>
      <span class="role-boundary">角色入口已隔离</span>
    </header>
    <RouterView />
  </div>
</template>

