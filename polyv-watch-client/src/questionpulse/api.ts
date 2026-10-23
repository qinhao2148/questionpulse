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
  my_option_key?: string | null;
  my_is_correct?: boolean | null;
}

interface Credentials {
  apiBase: string;
  sessionId: string;
  participantId: string;
  token: string;
}

function readCredentials(): Credentials | null {
  const query = new URLSearchParams(window.location.search);
  const sessionId = query.get('qpSessionId') || '';
  if (!sessionId) return null;
  const storageKey = `questionpulse.watch.${sessionId}`;
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
    apiBase: (query.get('qpApiBase') || 'http://127.0.0.1:8000/api/v1').replace(/\/$/, ''),
    sessionId,
    participantId: handoff.participantId,
    token: handoff.token,
  };
}

export const questionPulseCredentials = readCredentials();

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  if (!questionPulseCredentials) throw new Error('QuestionPulse 课堂身份不存在');
  const response = await fetch(`${questionPulseCredentials.apiBase}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${questionPulseCredentials.token}`,
      ...init.headers,
    },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || 'QuestionPulse 请求失败');
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
