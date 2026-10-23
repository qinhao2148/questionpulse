export interface QuestionPulseCluster {
  id: string;
  title: string;
  status: string;
  feedback_round: number;
  feedback: {
    round: number;
    my_result?: string | null;
    responses: number;
    understood: number;
    still_confused: number;
  };
  questions: Array<{ id: string }>;
}

export interface QuestionPulseSnapshot {
  id: string;
  title: string;
  status: string;
  clusters: QuestionPulseCluster[];
}

export interface QuestionPulseCheck {
  id: string;
  cluster_id: string;
  stem: string;
  options: Array<{ key: string; content: string }>;
  explanation?: string | null;
  correct_option_key?: string | null;
  my_option_key?: string | null;
  my_is_correct?: boolean | null;
}

interface Credentials {
  apiBase: string;
  sessionId: string;
  participantId: string;
  token: string;
}

const DEFAULT_API_BASE = 'http://127.0.0.1:8000/api/v1';
const LOCAL_HOSTS = ['127.0.0.1', 'localhost'];

/**
 * The API base arrives in the URL, so it is attacker-controllable: a crafted
 * "student link" could otherwise make this page post a student's name and join
 * code to a third-party host. Only same-host or localhost targets are accepted.
 */
function resolveApiBase(raw: string | null): string {
  if (!raw) return DEFAULT_API_BASE;
  try {
    const url = new URL(raw);
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return DEFAULT_API_BASE;
    const pageHost = window.location.hostname;
    const sameHost = url.hostname === pageHost;
    const bothLocal = LOCAL_HOSTS.includes(url.hostname) && LOCAL_HOSTS.includes(pageHost);
    if (!sameHost && !bothLocal) {
      console.warn('QuestionPulse 拒绝连接非本页来源的后端地址', url.origin);
      return DEFAULT_API_BASE;
    }
    return raw.replace(/\/$/, '');
  } catch {
    return DEFAULT_API_BASE;
  }
}

/** Backend error detail translated for students, who never see API docs. */
const ERROR_LABELS: Record<string, string> = {
  join_code_not_found: '没有找到这个课堂码，请和老师确认',
  session_ended: '这堂课已经结束了',
  session_not_found: '课堂不存在，请和老师确认课堂码',
  access_denied: '课堂身份已失效，请重新输入课堂码',
  access_expired: '课堂身份已过期，请重新输入课堂码',
  participant_not_in_session: '你已不在本课堂中，请重新加入',
  feedback_round_not_open: '本轮反馈已经结束',
  feedback_round_not_started: '老师还没有结束讲解',
  participant_not_feedback_target: '本轮反馈没有发给你',
  check_question_not_active: '这道检测已经结束',
  check_already_answered: '本题已经提交，不能重复作答',
  participant_not_check_target: '这道检测没有发给你',
  invalid_check_option: '选项无效，请刷新后重试',
};

export class QuestionPulseApiError extends Error {
  constructor(public code: string, message: string) {
    super(message);
    this.name = 'QuestionPulseApiError';
  }
}

function credentialKey(sessionId: string) {
  return `questionpulse.watch.${sessionId}`;
}

function readCredentials(): Credentials | null {
  const query = new URLSearchParams(window.location.search);
  const sessionId = query.get('qpSessionId') || '';
  if (!sessionId) return null;
  const storageKey = credentialKey(sessionId);
  const hash = new URLSearchParams(window.location.hash.replace(/^#/, ''));
  if (hash.get('token') && hash.get('participantId')) {
    sessionStorage.setItem(
      storageKey,
      JSON.stringify({ token: hash.get('token'), participantId: hash.get('participantId') }),
    );
    window.history.replaceState(
      null,
      document.title,
      `${window.location.pathname}${window.location.search}`,
    );
  }
  let handoff: { token?: string; participantId?: string } = {};
  try {
    handoff = JSON.parse(sessionStorage.getItem(storageKey) || '{}');
  } catch {
    return null;
  }
  if (!handoff.token || !handoff.participantId) return null;
  return {
    apiBase: resolveApiBase(query.get('qpApiBase')),
    sessionId,
    participantId: handoff.participantId,
    token: handoff.token,
  };
}

export const questionPulseCredentials = readCredentials();

/** Drop the stored identity so the panel can fall back to the join form. */
export function clearQuestionPulseCredentials() {
  const query = new URLSearchParams(window.location.search);
  const sessionId = query.get('qpSessionId') || questionPulseCredentials?.sessionId || '';
  if (sessionId) sessionStorage.removeItem(credentialKey(sessionId));
}

/** Reload into join mode, keeping only the (already validated) API base. */
export function questionPulseJoinUrl(duplicateTab = false) {
  const url = new URL(window.location.href);
  const apiBase = url.searchParams.get('qpApiBase');
  url.search = '';
  url.hash = '';
  if (apiBase) url.searchParams.set('qpApiBase', apiBase);
  url.searchParams.set('qpJoin', '1');
  if (duplicateTab) url.searchParams.set('qpDup', '1');
  return url.toString();
}

/**
 * Drop a viewer identity that this tab has no credentials for.
 *
 * The viewer id stays in the URL after joining, so a copied link (or a restored
 * session) can load the player as somebody else's POLYV viewer. Without our
 * token there is nothing to show for that student, so the safe move is to go
 * back to the join form instead of silently reusing the id.
 */
export function stripStaleViewerIdentity() {
  const url = new URL(window.location.href);
  const identityParams = [
    'viewerid',
    'name',
    'nickname',
    'externalViewerId',
    'qpIdentityNickname',
    'ts',
    'sign',
    'forceDirectAuth',
    'avatar',
    'param4',
    'param5',
  ];
  if (!identityParams.some(key => url.searchParams.has(key))) return false;
  identityParams.forEach(key => url.searchParams.delete(key));
  window.history.replaceState(null, document.title, `${url.pathname}${url.search}${url.hash}`);
  return true;
}

/**
 * A viewer key is minted per join attempt and kept only in memory.
 *
 * It used to live in localStorage, then in sessionStorage. Both are inherited:
 * a duplicated tab (and, for localStorage, every tab on the machine) carries the
 * same key, so the backend mapped two tabs onto one participant, both tabs got
 * one POLYV viewer id, and POLYV kicked the older one with "已在其他地方登录".
 * Nothing that survives a page load is safe here, and nothing needs to: after
 * joining, the tab identifies itself with the token, not with this key.
 */
let sessionViewerKey: string | null = null;

function mintViewerKey(): string {
  if (!sessionViewerKey) sessionViewerKey = crypto.randomUUID();
  return sessionViewerKey;
}

export async function joinQuestionPulseClassroom(joinCode: string, displayName: string) {
  const query = new URLSearchParams(window.location.search);
  const apiBase = resolveApiBase(query.get('qpApiBase'));
  const viewerKey = mintViewerKey();
  const response = await fetch(`${apiBase}/student/join`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      join_code: joinCode.trim().toUpperCase(),
      display_name: displayName.trim(),
      viewer_key: viewerKey,
    }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const code = String(payload.detail || '');
    throw new QuestionPulseApiError(code, ERROR_LABELS[code] || '加入课堂失败，请稍后重试');
  }
  const classroom = payload.data;
  if (!classroom.polyv_channel_id) throw new Error('课堂尚未绑定 POLYV 频道');
  if (!classroom.polyv_identity_auth) {
    throw new Error('课堂尚未配置保利威用户体系授权，请联系教师');
  }
  const identityAuth = classroom.polyv_identity_auth;
  const targetQuery = new URLSearchParams({
    channelId: classroom.polyv_channel_id,
    viewerid: classroom.polyv_viewer_id,
    name: displayName.trim(),
    externalViewerId: identityAuth.external_viewer_id,
    qpIdentityNickname: identityAuth.nickname,
    ts: String(identityAuth.ts),
    sign: identityAuth.sign,
    qpSessionId: classroom.session_id,
    qpApiBase: apiBase,
  });
  const handoff = new URLSearchParams({
    token: classroom.access_token,
    participantId: classroom.participant_id,
  });
  window.location.assign(
    `${window.location.pathname}?${targetQuery.toString()}#${handoff.toString()}`,
  );
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  if (!questionPulseCredentials) {
    throw new QuestionPulseApiError('no_credentials', '课堂身份不存在，请重新输入课堂码');
  }
  const response = await fetch(`${questionPulseCredentials.apiBase}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${questionPulseCredentials.token}`,
      ...init.headers,
    },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const code = String(payload.detail || '');
    throw new QuestionPulseApiError(
      code,
      ERROR_LABELS[code] ||
        (response.status >= 500 ? '课堂服务暂时不可用，请稍后重试' : '请求未完成'),
    );
  }
  return payload as T;
}

export function fetchQuestionPulseSnapshot() {
  const credentials = questionPulseCredentials!;
  return request<QuestionPulseSnapshot>(`/sessions/${credentials.sessionId}/student-snapshot`);
}

export function fetchQuestionPulseChecks() {
  const credentials = questionPulseCredentials!;
  return request<QuestionPulseCheck[]>(`/sessions/${credentials.sessionId}/checks/active`);
}

export function sendQuestionPulseFeedback(clusterId: string, round: number, result: string) {
  const credentials = questionPulseCredentials!;
  return request(`/sessions/${credentials.sessionId}/clusters/${clusterId}/feedback`, {
    method: 'PUT',
    body: JSON.stringify({ participant_id: credentials.participantId, round, result }),
  });
}

export function answerQuestionPulseCheck(checkId: string, optionKey: string) {
  const credentials = questionPulseCredentials!;
  return request<{
    data: { is_correct: boolean; correct_option_key: string; explanation: string };
  }>(`/sessions/${credentials.sessionId}/checks/${checkId}/answer`, {
    method: 'PUT',
    body: JSON.stringify({ participant_id: credentials.participantId, option_key: optionKey }),
  });
}

export function uploadQuestionPulseChat(message: { id: string; content: string; time?: number }) {
  const credentials = questionPulseCredentials!;
  return request(`/sessions/${credentials.sessionId}/chat-messages`, {
    method: 'POST',
    body: JSON.stringify({
      external_id: message.id,
      content: message.content,
      occurred_at: new Date(message.time || Date.now()).toISOString(),
    }),
  });
}
