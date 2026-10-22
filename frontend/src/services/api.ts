export interface HealthResponse {
  status: string
  service: string
  environment: string
}

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || '/api/v1'

const teacherTokenKey = (sessionId: string) => `questionpulse.teacher_token.${sessionId}`
const joinCodeKey = (sessionId: string) => `questionpulse.join_code.${sessionId}`
const studentTokenKey = (sessionId: string) => `questionpulse.student_token.${sessionId}`

export function saveTeacherAccess(sessionId: string, token: string, joinCode: string) {
  sessionStorage.setItem(teacherTokenKey(sessionId), token)
  sessionStorage.setItem(joinCodeKey(sessionId), joinCode)
}

export function getJoinCode(sessionId: string) {
  return sessionStorage.getItem(joinCodeKey(sessionId)) || ''
}

function bearer(token: string | null): HeadersInit {
  return token ? { Authorization: `Bearer ${token}` } : {}
}

function teacherHeaders(sessionId: string): HeadersInit {
  return bearer(sessionStorage.getItem(teacherTokenKey(sessionId)))
}

function studentHeaders(sessionId: string): HeadersInit {
  return bearer(sessionStorage.getItem(studentTokenKey(sessionId)))
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
      cannot_detach_only_question: '疑问簇只有一条问题，无法继续拆分',
      question_not_pending: '该问题当前无需重试', version_conflict: '数据已更新，请刷新后重试',
      check_already_answered: '本题已经提交，答案不能再次修改',
      polyv_credentials_not_configured: 'POLYV App ID 或 App Secret 尚未配置',
      polyv_channel_not_configured: '尚未配置 POLYV 测试频道号',
      polyv_api_unavailable: 'POLYV API 调用失败，请查看接入状态后重试',
    }
    throw new Error(labels[body?.detail || ''] || body?.detail || `请求失败：${response.status}`)
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
  const result = await jsonRequest<{ data: { id: string; teacher_token: string; join_code: string } }>('/sessions', {
    method: 'POST', body: JSON.stringify({ title }),
  })
  saveTeacherAccess(result.data.id, result.data.teacher_token, result.data.join_code)
  return { id: result.data.id, join_code: result.data.join_code }
}

export async function joinClassroom(sessionId: string, viewerKey: string, joinCode?: string) {
  const result = await jsonRequest<{ data: { participant_id: string; access_token: string } }>(
    `/sessions/${sessionId}/join`,
    { method: 'POST', body: JSON.stringify({ viewer_key: viewerKey, join_code: joinCode || null }) },
  )
  sessionStorage.setItem(studentTokenKey(sessionId), result.data.access_token)
  return { participant_id: result.data.participant_id }
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

