export interface HealthResponse {
  status: string
  service: string
  environment: string
}

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || '/api/v1'

const teacherPortalTokenKey = 'questionpulse.teacher_portal_token'

/** Shown whenever the server rejects a stale teacher portal token. */
export const TEACHER_LOGIN_REQUIRED_MESSAGE = '教师登录已过期，请重新登录教师课堂中心'

export function getTeacherPortalToken() {
  return localStorage.getItem(teacherPortalTokenKey) || ''
}

export function hasTeacherAccess() { return Boolean(getTeacherPortalToken()) }

export function getTeacherAccessToken() { return getTeacherPortalToken() }

export function logoutTeacher() {
  localStorage.removeItem(teacherPortalTokenKey)
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
  rag_answers?: RagAnswerView[]
  published_answers?: PublishedAnswer[]
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
  knowledge_backed?: boolean
  explanation: string | null
  correct_option_key: string | null
  target_count: number
  response_count: number
  correct_count: number
  my_option_key: string | null
  my_is_correct: boolean | null
}

export interface KnowledgeGapItem {
  question: string
  answer_excerpt: string | null
  reason: string | null
  kind: 'rejected' | 'failed' | 'insufficient'
  occurred_at: string
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
  knowledge_gaps?: KnowledgeGapItem[]
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
      knowledge_snapshot_frozen: '本课堂已经开始使用资料答疑，资料范围已锁定；如需更换请创建新课堂',
      version_referenced_by_snapshots: '这份资料仍被历史课堂引用，不能物理删除',
      unsupported_format: '暂不支持该文件格式，请上传 PDF、Word、PPT、Markdown 或文本文件',
      file_too_large: '文件太大，请上传 50MB 以内的文档',
      knowledge_base_not_found: '知识库不存在或已归档',
      document_not_found: '文档不存在或已被删除',
      version_not_found: '文档版本不存在或已被删除',
      version_not_ready: '该版本尚未完成索引，不能启用',
      job_already_queued: '任务已经在队列中，请稍候',
      document_not_in_base: '该文档不属于所选知识库',
      job_not_found: '处理任务不存在',
      job_running: '任务正在处理中，请稍候',
      rag_answer_not_found: 'AI 答案不存在或已被删除',
      rag_answer_not_draft: '该答案已被处理过，请刷新后查看最新状态',
      rag_answer_not_publishable: '该答案当前不能发布，请刷新后查看最新状态',
      rag_answer_insufficient: '资料依据不足，不能发布给学生',
      rag_answer_already_published: '该答案已经发布，无法撤回',
      rag_answer_has_no_citations: '这份答案没有可追溯的资料引用，不能发布给学生',
      invalid_action: '操作无效，请刷新后重试',
      name_required: '请填写名称',
      query_required: '请输入要检索的内容',
    }
    const knownMessage = labels[(body?.detail || '').split(':')[0]]
      || labels[body?.detail || '']
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

export async function updateJoinCode(sessionId: string, joinCode: string) {
  const result = await jsonRequest<{ data: { join_code: string } }>(`/sessions/${sessionId}/join-code`, {
    method: 'PATCH', headers: teacherHeaders(sessionId), body: JSON.stringify({ join_code: joinCode }),
  })
  return result.data.join_code
}

export function fetchTeacherSnapshot(sessionId: string): Promise<Snapshot> {
  return jsonRequest<Snapshot>(`/sessions/${sessionId}/teacher-snapshot`, {
    headers: teacherHeaders(sessionId),
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
  return jsonRequest<{ data: { accepted: number; duplicates: number; fetched: number; skipped: number; integration_status: string } }>(
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

export function fetchReport(sessionId: string): Promise<SessionReport> {
  return jsonRequest<SessionReport>(`/sessions/${sessionId}/report`, {
    headers: teacherHeaders(sessionId),
  })
}

// ---------------------------------------------------------------- knowledge

export interface KnowledgeVersionView {
  id: string
  version_number: number
  original_file_name: string
  status: string
  error_code: string | null
  chunk_count: number | null
  embedding_model: string | null
  embedding_dimensions: number | null
  file_sha256: string | null
  is_active: boolean
  created_at: string
  published_at: string | null
}

export interface KnowledgeDocumentView {
  id: string
  knowledge_base_id: string
  document_key: string
  title: string
  description: string | null
  status: string
  tags: string[]
  owner_session_id: string | null
  current_version: KnowledgeVersionView | null
  versions: KnowledgeVersionView[]
  created_at: string
}

export interface KnowledgeBaseView {
  id: string
  name: string
  description: string | null
  visibility: string
  status: string
  document_count: number
  created_at: string
}

export interface KnowledgeStatusView {
  // healthy: qdrant connected; degraded: connected but on the hash fallback
  // embedder; unavailable: qdrant unreachable, upload/search disabled.
  status: 'healthy' | 'degraded' | 'unavailable'
  error_code: string | null
  embedding: {
    provider: string
    model_name: string
    dimensions: number
    degraded: boolean
  }
  vector_store: string
}

export interface KnowledgeSearchHit {
  chunk_id: string
  document_title: string
  version_number: number
  section_path: string | null
  page_start: number | null
  page_end: number | null
  score: number
  content: string
}

export interface CitationView {
  chunk_id: string
  document_title: string
  version_number: number
  section_path: string | null
  page_start: number | null
  page_end: number | null
  score: number | null
  location: string
  content: string
}

export interface RagAnswerView {
  id: string
  question_id: string | null
  cluster_id: string | null
  question_content: string | null
  answer: string | null
  confidence: number | null
  insufficient_evidence: boolean
  answer_status: string
  model: string | null
  error_code: string | null
  citations: CitationView[]
  created_at: string
}

export interface PublishedAnswer {
  answer_id: string
  question_id: string | null
  question_content: string | null
  answer: string | null
  citations: CitationView[]
  published_at: string | null
}

export interface BindingView {
  id: string
  knowledge_base_id: string
  knowledge_base_name: string | null
  document_id: string | null
  document_title: string | null
  binding_scope: string
  follow_latest: boolean
}

export interface SnapshotDocumentView {
  document_id: string
  document_title: string
  document_key: string
  document_version_id: string
  version_number: number
  status: string
  chunk_count: number | null
  embedding_model: string | null
  published_at: string | null
}

export interface SessionKnowledgeView {
  bindings: BindingView[]
  snapshot_documents: SnapshotDocumentView[]
  frozen_at: string | null
}

export interface BindingInput {
  knowledge_base_id: string
  document_id: string | null
  binding_scope: 'whole_knowledge_base' | 'single_document'
  follow_latest: boolean
}

export function fetchKnowledgeStatus(): Promise<KnowledgeStatusView> {
  return jsonRequest<KnowledgeStatusView>('/knowledge/status', {
    headers: teacherPortalHeaders(),
  })
}

export function fetchKnowledgeBases(): Promise<KnowledgeBaseView[]> {
  return jsonRequest<{ data: KnowledgeBaseView[] }>('/knowledge-bases', {
    headers: teacherPortalHeaders(),
  }).then((result) => result.data)
}

export function createKnowledgeBase(name: string, description = ''): Promise<KnowledgeBaseView> {
  return jsonRequest<{ data: KnowledgeBaseView }>('/knowledge-bases', {
    method: 'POST',
    headers: teacherPortalHeaders(),
    body: JSON.stringify({ name, description }),
  }).then((result) => result.data)
}

export function archiveKnowledgeBase(baseId: string) {
  return jsonRequest(`/knowledge-bases/${baseId}/archive`, {
    method: 'POST', headers: teacherPortalHeaders(), body: '{}',
  })
}

export function fetchKnowledgeDocuments(baseId: string): Promise<KnowledgeDocumentView[]> {
  return jsonRequest<{ data: KnowledgeDocumentView[] }>(`/knowledge-bases/${baseId}/documents`, {
    headers: teacherPortalHeaders(),
  }).then((result) => result.data)
}

export function uploadKnowledgeDocument(
  baseId: string, file: File, title: string, documentKey: string, tags: string,
) {
  const form = new FormData()
  form.append('file', file)
  if (title) form.append('title', title)
  if (documentKey) form.append('document_key', documentKey)
  if (tags) form.append('tags', tags)
  return fetch(`${apiBaseUrl}/knowledge-bases/${baseId}/documents`, {
    method: 'POST',
    headers: teacherPortalHeaders(),
    body: form,
  }).then(async (response) => {
    if (!response.ok) {
      const body = await response.json().catch(() => null) as { detail?: unknown } | null
      throw new Error(formatErrorDetail(body?.detail, response.status))
    }
    return response.json() as Promise<{ data: { document_id: string; version_id: string; job_id: string } }>
  })
}

export function uploadDocumentVersion(documentId: string, file: File, title: string) {
  const form = new FormData()
  form.append('file', file)
  if (title) form.append('title', title)
  return fetch(`${apiBaseUrl}/knowledge-documents/${documentId}/versions`, {
    method: 'POST',
    headers: teacherPortalHeaders(),
    body: form,
  }).then(async (response) => {
    if (!response.ok) {
      const body = await response.json().catch(() => null) as { detail?: unknown } | null
      throw new Error(formatErrorDetail(body?.detail, response.status))
    }
    return response.json() as Promise<{ data: { version_id: string; job_id: string } }>
  })
}

export function retryDocumentVersion(versionId: string) {
  return jsonRequest<{ data: { job_id: string; status: string } }>(
    `/knowledge-document-versions/${versionId}/retry`,
    { method: 'POST', headers: teacherPortalHeaders(), body: '{}' },
  )
}

export function activateDocumentVersion(documentId: string, versionId: string) {
  return jsonRequest<{ data: { document_id: string; current_version_id: string } }>(
    `/knowledge-documents/${documentId}/versions/${versionId}/activate`,
    { method: 'POST', headers: teacherPortalHeaders(), body: '{}' },
  )
}

export function retryKnowledgeJob(jobId: string) {
  return jsonRequest<{ data: { job_id: string; status: string } }>(`/knowledge/jobs/${jobId}/retry`, {
    method: 'POST', headers: teacherPortalHeaders(), body: '{}',
  })
}

export function archiveDocumentVersion(versionId: string) {
  return jsonRequest(`/knowledge-document-versions/${versionId}/archive`, {
    method: 'POST', headers: teacherPortalHeaders(), body: '{}',
  })
}

export function searchKnowledgePreview(baseIds: string[], query: string): Promise<KnowledgeSearchHit[]> {
  return jsonRequest<{ data: { results: KnowledgeSearchHit[] } }>('/knowledge/search-preview', {
    method: 'POST',
    headers: teacherPortalHeaders(),
    body: JSON.stringify({ knowledge_base_ids: baseIds, query }),
  }).then((result) => result.data.results)
}

export function fetchSessionKnowledge(sessionId: string): Promise<SessionKnowledgeView> {
  return jsonRequest<{ data: SessionKnowledgeView }>(`/sessions/${sessionId}/knowledge`, {
    headers: teacherHeaders(sessionId),
  }).then((result) => result.data)
}

export function replaceSessionBindings(sessionId: string, bindings: BindingInput[]) {
  return jsonRequest<{ data: { binding_count: number } }>(`/sessions/${sessionId}/knowledge/bindings`, {
    method: 'PUT',
    headers: teacherHeaders(sessionId),
    body: JSON.stringify({ bindings }),
  })
}

export function fetchRagAnswers(sessionId: string): Promise<RagAnswerView[]> {
  return jsonRequest<{ data: RagAnswerView[] }>(`/sessions/${sessionId}/rag-answers`, {
    headers: teacherHeaders(sessionId),
  }).then((result) => result.data)
}

export function actOnRagAnswer(
  sessionId: string, answerId: string, action: string, reason?: string,
) {
  return jsonRequest<{ data: { id: string; answer_status: string } }>(
    `/sessions/${sessionId}/rag-answers/${answerId}/action`,
    {
      method: 'POST',
      headers: teacherHeaders(sessionId),
      body: JSON.stringify({ action, reason: reason || null }),
    },
  )
}

export function regenerateRagAnswer(sessionId: string, questionId: string) {
  return jsonRequest<{ data: { status: string } }>(
    `/sessions/${sessionId}/questions/${questionId}/rag-answer`,
    { method: 'POST', headers: teacherHeaders(sessionId), body: '{}' },
  )
}

function formatErrorDetail(detail: unknown, status: number): string {
  const labels: Record<string, string> = {
    unsupported_format: '暂不支持该文件格式，请上传 PDF、Word、PPT、Markdown 或文本文件',
    file_too_large: '文件太大，请上传 50MB 以内的文档',
    knowledge_base_not_found: '知识库不存在或已归档',
  }
  if (typeof detail === 'string') {
    const key = detail.split(':')[0]
    if (labels[key]) return labels[key]
    if (key === 'unsupported_format') return labels.unsupported_format
  }
  if (status >= 500) return '课堂服务暂时不可用，请稍后重试'
  return '请求未完成，请检查入口后重试'
}

