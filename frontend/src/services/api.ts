export interface HealthResponse {
  status: string
  service: string
  environment: string
}

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || '/api/v1'

const studentTokenKey = (sessionId: string) => `questionpulse.student_token.${sessionId}`
const studentParticipantKey = (sessionId: string) => `questionpulse.student_participant.${sessionId}`
const teacherPortalTokenKey = 'questionpulse.teacher_portal_token'
const studentClassroomsKey = 'questionpulse.student_classrooms'

/** Shown whenever the server rejects a stale teacher portal token. */
export const TEACHER_LOGIN_REQUIRED_MESSAGE = '教师登录已过期，请重新登录教师课堂中心'

export interface LocalClassroomRecord {
  id: string
  title: string
  updated_at: string
}

function readRecords(key: string): LocalClassroomRecord[] {
  try { return JSON.parse(localStorage.getItem(key) || '[]') as LocalClassroomRecord[] } catch { return [] }
}

function saveRecord(key: string, record: LocalClassroomRecord) {
  const records = readRecords(key).filter((item) => item.id !== record.id)
  localStorage.setItem(key, JSON.stringify([record, ...records].slice(0, 30)))
}

export const listStudentClassrooms = () => readRecords(studentClassroomsKey)

export function getTeacherPortalToken() {
  return localStorage.getItem(teacherPortalTokenKey) || ''
}

export function hasTeacherAccess() { return Boolean(getTeacherPortalToken()) }

export function getTeacherAccessToken() { return getTeacherPortalToken() }

export function logoutTeacher() {
  localStorage.removeItem(teacherPortalTokenKey)
}

export function rememberStudentClassroom(sessionId: string, title: string) {
  saveRecord(studentClassroomsKey, { id: sessionId, title, updated_at: new Date().toISOString() })
}

export function getStudentParticipant(sessionId: string) {
  return localStorage.getItem(studentParticipantKey(sessionId)) || ''
}

function bearer(token: string | null): HeadersInit {
  return token ? { Authorization: `Bearer ${token}` } : {}
}

function teacherHeaders(sessionId: string): HeadersInit {
  void sessionId
  return bearer(getTeacherAccessToken())
}

function teacherPortalHeaders(): HeadersInit {
  return bearer(getTeacherPortalToken())
}

function studentHeaders(sessionId: string): HeadersInit {
  return bearer(sessionStorage.getItem(studentTokenKey(sessionId)) || localStorage.getItem(studentTokenKey(sessionId)))
}

export interface Question {
  id: string
  participant_id: string
  content: string
  source: string
  external_id: string | null
  occurred_at: string | null
  cluster_id: string | null
  processing_status: string
  assignment_method: string | null
  similarity: number | null
  embedding_model: string | null
  created_at: string
}

export interface Cluster {
  id: string
  title: string
  status: string
  version: number
  feedback_round: number
  feedback: FeedbackSummary
  feedback_history?: FeedbackSummary[]
  participant_count: number
  question_count: number
  confusion_score: number
  confusion_level: 'low' | 'medium' | 'high'
  confusion_breakdown: {
    participant_ratio: number
    recent_activity: number
    wait_pressure: number
    still_confused_ratio: number
    check_error_ratio: number
  }
  ai_normalized_intent: string | null
  ai_semantic_reason: string | null
  ai_model: string | null
  questions: Question[]
}

export interface FeedbackSummary {
  round: number
  targets: number
  responses: number
  understood: number
  still_confused: number
  my_result: 'understood' | 'still_confused' | null
}

export interface Snapshot {
  id: string
  title: string
  join_code: string | null
  status: string
  mode: string
  integration_status: string
  polyv_channel_id: string | null
  polyv_session_id: string | null
  last_synced_at: string | null
  integration_error: string | null
  degraded_at: string | null
  clusters: Cluster[]
  pending_questions: Question[]
}

export interface CheckOption {
  key: string
  content: string
}

export interface CheckQuestion {
  id: string
  cluster_id: string
  feedback_round: number
  status: 'draft' | 'active' | 'closed'
  stem: string
  options: CheckOption[]
  source: string
  explanation: string | null
  correct_option_key: string | null
  target_count: number
  response_count: number
  correct_count: number
  my_option_key: string | null
  my_is_correct: boolean | null
}

export interface SessionReport {
  id: string
  title: string
  generated_at: string
  status: string
  ended_at: string | null
  question_count: number
  viewer_count: number
  active_viewer_count: number
  asker_count: number
  silent_viewer_count: number
  ask_rate: number
  participant_count: number
  cluster_count: number
  status_counts: Record<string, number>
  feedback_targets: number
  feedback_responses: number
  feedback_coverage: number
  understood: number
  still_confused: number
  check_targets: number
  check_responses: number
  check_correct: number
  check_accuracy: number
  clusters: Cluster[]
  follow_ups: Cluster[]
  timeline: Array<{
    kind: string
    cluster_id: string | null
    cluster_title: string | null
    detail: string
    occurred_at: string
  }>
  ai_insights: Array<{
    cluster_id: string
    cluster_title: string
    normalized_intent: string
    semantic_reason: string
    recommendation: string
    model: string
  }>
}

export interface TeacherClassroomSummary {
  id: string
  title: string
  status: string
  polyv_channel_id: string | null
  join_code: string | null
  question_count: number
  cluster_count: number
  created_at: string
  ended_at: string | null
}

export interface ChatReviewItem {
  id: string
  content: string
  confidence: number
  normalized_intent: string
  suggested_question: string | null
  reason: string
  occurred_at: string
}

async function jsonRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null
    const labels: Record<string, string> = {
      session_ended: '课堂已结束', session_not_found: '课堂不存在',
      access_denied: '没有访问该页面或操作的权限', invalid_join_code: '课堂加入码不正确',
      teacher_login_required: TEACHER_LOGIN_REQUIRED_MESSAGE,
      invalid_teacher_credentials: '教师账号或密码不正确',
      join_code_not_found: '没有找到使用该课堂码的进行中课堂',
      join_code_in_use: '该课堂码已被其他课堂使用，请换一个',
      cannot_detach_only_question: '疑问簇只有一条问题，无法继续拆分',
      question_not_pending: '该问题当前无需重试',
      check_already_answered: '本题已经提交，答案不能再次修改',
      cluster_version_conflict: '这条疑问刚被别的操作更新过，请刷新后重试',
      cluster_not_found: '这条疑问不存在或已被删除',
      question_not_found: '这条问题不存在或已被删除',
      check_question_not_found: '这道检测题不存在或已被删除',
      check_question_not_active: '这道检测已经结束，不能再作答',
      invalid_status_transition: '当前状态不支持这一步操作，请刷新后再试',
      invalid_check_option: '选择的选项无效，请刷新后重新作答',
      feedback_round_not_open: '本轮反馈已经结束，无法再提交',
      feedback_round_not_started: '教师还没有结束讲解，暂时不能提交理解反馈',
      participant_not_feedback_target: '本轮反馈没有发给你，无法提交',
      participant_not_check_target: '这道检测没有发给你，无法作答',
      participant_not_in_session: '你已不在本课堂中，请重新加入',
      question_has_no_cluster: '这条问题还没有归入任何疑问主题',
      question_has_no_embedding: '这条问题缺少语义向量，暂时无法拆分',
      polyv_credentials_not_configured: '直播平台授权信息尚未配置',
      polyv_channel_not_configured: '尚未配置直播频道',
      polyv_api_unavailable: '直播互动暂时无法同步，请稍后重试',
    }
    const knownMessage = labels[body?.detail || '']
    if (body?.detail === 'teacher_login_required') {
      // The stored token is no longer usable, so drop it. Keeping it only makes
      // every later request fail the same way with no way back to the login form.
      logoutTeacher()
      window.dispatchEvent(new CustomEvent('questionpulse:teacher-login-required'))
    }
    if (knownMessage) throw new Error(knownMessage)
    if (response.status >= 500) throw new Error('课堂服务暂时不可用，请稍后重试')
    throw new Error(body?.detail || '请求未完成，请检查入口后重试')
  }
  return response.json() as Promise<T>
}

export async function fetchHealth(): Promise<HealthResponse> {
  const response = await fetch(`${apiBaseUrl}/health/live`)
  if (!response.ok) {
    throw new Error(`后端返回 ${response.status}`)
  }
  return response.json() as Promise<HealthResponse>
}

export async function createClassroom(title: string): Promise<{ id: string; join_code: string }> {
  const result = await jsonRequest<{ data: { id: string; join_code: string } }>('/sessions', {
    method: 'POST', headers: teacherPortalHeaders(), body: JSON.stringify({ title }),
  })
  return { id: result.data.id, join_code: result.data.join_code }
}

export async function loginTeacher(username: string, password: string) {
  const result = await jsonRequest<{ data: { access_token: string } }>('/teacher/login', {
    method: 'POST', body: JSON.stringify({ username, password }),
  })
  localStorage.setItem(teacherPortalTokenKey, result.data.access_token)
}

export function fetchTeacherClassrooms(): Promise<TeacherClassroomSummary[]> {
  return jsonRequest<TeacherClassroomSummary[]>('/teacher/sessions', {
    headers: teacherPortalHeaders(),
  })
}

export async function joinClassroomByCode(joinCode: string, displayName: string, viewerKey: string) {
  const result = await jsonRequest<{ data: { session_id: string; session_title: string; participant_id: string; access_token: string; join_code: string; polyv_channel_id: string | null; polyv_session_id: string | null; polyv_viewer_id: string } }>(
    '/student/join',
    { method: 'POST', body: JSON.stringify({ join_code: joinCode, display_name: displayName, viewer_key: viewerKey }) },
  )
  const sessionId = result.data.session_id
  sessionStorage.setItem(studentTokenKey(sessionId), result.data.access_token)
  localStorage.setItem(studentTokenKey(sessionId), result.data.access_token)
  localStorage.setItem(studentParticipantKey(sessionId), result.data.participant_id)
  rememberStudentClassroom(sessionId, result.data.session_title)
  return result.data
}

export async function updateJoinCode(sessionId: string, joinCode: string) {
  const result = await jsonRequest<{ data: { join_code: string } }>(`/sessions/${sessionId}/join-code`, {
    method: 'PATCH', headers: teacherHeaders(sessionId), body: JSON.stringify({ join_code: joinCode }),
  })
  return result.data.join_code
}

export async function submitQuestion(
  sessionId: string, participantId: string, content: string, requestId: string,
) {
  const result = await jsonRequest<{ data: Question }>(`/sessions/${sessionId}/questions`, {
    method: 'POST',
    headers: studentHeaders(sessionId),
    body: JSON.stringify({ participant_id: participantId, client_request_id: requestId, content }),
  })
  return result.data
}

export function fetchStudentSnapshot(sessionId: string): Promise<Snapshot> {
  return jsonRequest<Snapshot>(`/sessions/${sessionId}/student-snapshot`, {
    headers: studentHeaders(sessionId),
  })
}

export function fetchTeacherSnapshot(sessionId: string): Promise<Snapshot> {
  return jsonRequest<Snapshot>(`/sessions/${sessionId}/teacher-snapshot`, {
    headers: teacherHeaders(sessionId),
  })
}

export function fetchStudentChecks(sessionId: string): Promise<CheckQuestion[]> {
  return jsonRequest<CheckQuestion[]>(`/sessions/${sessionId}/checks/active`, {
    headers: studentHeaders(sessionId),
  })
}

export function fetchTeacherChecks(sessionId: string): Promise<CheckQuestion[]> {
  return jsonRequest<CheckQuestion[]>(`/sessions/${sessionId}/checks`, {
    headers: teacherHeaders(sessionId),
  })
}

export function fetchChatReviewQueue(sessionId: string): Promise<ChatReviewItem[]> {
  return jsonRequest<{ data: ChatReviewItem[] }>(`/sessions/${sessionId}/chat-messages/review`, {
    headers: teacherHeaders(sessionId),
  }).then((result) => result.data)
}

export function reviewChatMessage(sessionId: string, messageId: string, action: 'promote' | 'ignore') {
  return jsonRequest(`/sessions/${sessionId}/chat-messages/${messageId}/review`, {
    method: 'POST', headers: teacherHeaders(sessionId), body: JSON.stringify({ action }),
  })
}

export function generateCheck(sessionId: string, clusterId: string): Promise<CheckQuestion> {
  return jsonRequest<CheckQuestion>(`/sessions/${sessionId}/clusters/${clusterId}/checks/generate`, {
    method: 'POST', headers: teacherHeaders(sessionId), body: '{}',
  })
}

export function approveCheck(sessionId: string, checkId: string) {
  return jsonRequest<{ data: CheckQuestion }>(`/sessions/${sessionId}/checks/${checkId}/approve`, {
    method: 'POST', headers: teacherHeaders(sessionId), body: '{}',
  })
}

export function closeCheck(sessionId: string, checkId: string) {
  return jsonRequest<{ data: CheckQuestion }>(`/sessions/${sessionId}/checks/${checkId}/close`, {
    method: 'POST', headers: teacherHeaders(sessionId), body: '{}',
  })
}

export function answerCheck(
  sessionId: string, checkId: string, participantId: string, optionKey: string,
) {
  return jsonRequest<{ data: { selected_option_key: string; is_correct: boolean; correct_option_key: string; explanation: string } }>(
    `/sessions/${sessionId}/checks/${checkId}/answer`,
    {
      method: 'PUT', headers: studentHeaders(sessionId),
      body: JSON.stringify({ participant_id: participantId, option_key: optionKey }),
    },
  )
}

export async function detachQuestion(sessionId: string, questionId: string) {
  return jsonRequest<{ data: { cluster_id: string } }>(
    `/sessions/${sessionId}/questions/${questionId}/detach`,
    { method: 'POST', headers: teacherHeaders(sessionId), body: '{}' },
  )
}

export async function retryQuestion(sessionId: string, questionId: string) {
  return jsonRequest<{ data: Question }>(`/sessions/${sessionId}/questions/${questionId}/retry`, {
    method: 'POST', headers: teacherHeaders(sessionId), body: '{}',
  })
}

export async function endClassroom(sessionId: string) {
  return jsonRequest<{ data: { status: string; ended_at: string } }>(`/sessions/${sessionId}/end`, {
    method: 'POST', headers: teacherHeaders(sessionId), body: '{}',
  })
}

export async function verifyPolyvContract(sessionId: string) {
  const suffix = sessionId.slice(0, 8)
  return jsonRequest<{ data: { accepted: number; duplicates: number; integration_status: string } }>(
    `/sessions/${sessionId}/integrations/polyv/events`,
    {
      method: 'POST',
      headers: teacherHeaders(sessionId),
      body: JSON.stringify({
        environment: 'contract_test', channel_id: 'contract-channel',
        polyv_session_id: 'contract-session',
        events: [
          { external_id: `qa-${suffix}-1`, viewer_key: 'contract-viewer-a', source: 'polyv_qa', occurred_at: new Date().toISOString(), content: '递归出口为什么必须存在？' },
          { external_id: `qa-${suffix}-2`, viewer_key: 'contract-viewer-b', source: 'polyv_qa', occurred_at: new Date().toISOString(), content: '没有 base case 时为什么停不下来？' },
        ],
      }),
    },
  )
}

export async function runIntegrationDrill(sessionId: string, action: 'degrade' | 'recover') {
  return jsonRequest<{ data: { integration_status: string; integration_error: string | null } }>(
    `/sessions/${sessionId}/integrations/polyv/drill`,
    { method: 'POST', headers: teacherHeaders(sessionId), body: JSON.stringify({ environment: 'contract_test', action }) },
  )
}

export async function syncPolyvQuestions(sessionId: string) {
  return jsonRequest<{ data: { accepted: number; duplicates: number; fetched: number; integration_status: string } }>(
    `/sessions/${sessionId}/integrations/polyv/sync`,
    { method: 'POST', headers: teacherHeaders(sessionId), body: '{}' },
  )
}

export async function syncPolyvChatMessages(sessionId: string) {
  return jsonRequest<{ data: { accepted: number; duplicates: number; fetched: number; integration_status: string } }>(
    `/sessions/${sessionId}/integrations/polyv/chat/sync`,
    { method: 'POST', headers: teacherHeaders(sessionId), body: '{}' },
  )
}

export async function retryPendingQuestions(sessionId: string) {
  return jsonRequest<{ data: { attempted: number; recovered: number; remaining: number } }>(
    `/sessions/${sessionId}/questions/retry-pending`, { method: 'POST', headers: teacherHeaders(sessionId), body: '{}' },
  )
}

export async function updateClusterStatus(
  sessionId: string, clusterId: string, status: string, expectedVersion: number,
) {
  return jsonRequest<{ data: { status: string; version: number; feedback_round: number } }>(
    `/sessions/${sessionId}/clusters/${clusterId}/status`,
    { method: 'PATCH', headers: teacherHeaders(sessionId), body: JSON.stringify({ status, expected_version: expectedVersion }) },
  )
}

export async function sendFeedback(
  sessionId: string,
  clusterId: string,
  participantId: string,
  round: number,
  result: 'understood' | 'still_confused',
) {
  return jsonRequest<{ data: { result: string } }>(
    `/sessions/${sessionId}/clusters/${clusterId}/feedback`,
    { method: 'PUT', headers: studentHeaders(sessionId), body: JSON.stringify({ participant_id: participantId, round, result }) },
  )
}

export function fetchReport(sessionId: string): Promise<SessionReport> {
  return jsonRequest<SessionReport>(`/sessions/${sessionId}/report`, {
    headers: teacherHeaders(sessionId),
  })
}

