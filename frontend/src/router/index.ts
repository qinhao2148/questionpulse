import { createRouter, createWebHistory } from 'vue-router'

const HomePage = () => import('../views/HomePage.vue')
const ReportPage = () => import('../views/ReportPage.vue')
const StudentPage = () => import('../views/StudentPage.vue')
const StudentHomePage = () => import('../views/StudentHomePage.vue')
const TeacherPage = () => import('../views/TeacherPage.vue')

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: HomePage },
    { path: '/student', component: StudentHomePage },
    {
      path: '/student/:sessionId',
      component: StudentPage,
    },
    {
      path: '/teacher/:sessionId',
      component: TeacherPage,
    },
    {
      path: '/report/:sessionId',
      component: ReportPage,
    },
  ],
})

