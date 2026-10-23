import {
  clearQuestionPulseCredentials,
  questionPulseCredentials,
  questionPulseJoinUrl,
  stripStaleViewerIdentity,
} from './api';

/**
 * 保利威一个观众只允许一个活跃会话。
 *
 * 同一个 viewer id 在第二个标签页登录时，POLYV 会把先开的那个踢到
 * “浏览器重复打开了相同的标签页 / 当前账号已在其他地方登录” 错误页。
 * 我们这边能做的有两件事：
 *
 * 1. 没有本课堂凭证的标签页，不要继续使用 URL 里遗留的 viewer id（那是别人的身份），
 *    也不要几个标签页共用同一个“游客”身份 —— 每个标签页单独领一个匿名 id。
 * 2. 有凭证的标签页，用 BroadcastChannel 和其他标签页对一下：同一个学生已经有
 *    标签页在播，就把后来者送回加入表单，让它换一个名字重新进入。
 *
 * BroadcastChannel 是唯一按标签页隔离、又不会被“复制标签页”带走的浏览器能力，
 * 所以重复判定用它，而不是 localStorage / sessionStorage（都会被复制）。
 */
const PROBE_TIMEOUT_MS = 350;

type TabMessage = {
  type: 'probe' | 'alive';
  tabId: string;
  participantId: string;
};

declare global {
  interface Window {
    // Anchor for the probe channel: the tab has to keep answering other tabs
    // for its whole lifetime, so the reference outlives this function.
    __questionPulseTabChannels?: BroadcastChannel[];
  }
}

let tabId: string | null = null;

function currentTabId() {
  if (!tabId) tabId = crypto.randomUUID();
  return tabId;
}

/**
 * 没有凭证时，给这个标签页安排一个独立的游客身份。
 *
 * 不加这一步时，多个没带 viewerid 的标签页会被 POLYV 当成同一个游客，
 * 一样会互相踢下线，而且显示的是 POLYV 随机分配的昵称（比如“小龙虾”）。
 */
function ensureVisitorViewerId() {
  const url = new URL(window.location.href);
  if (url.searchParams.get('viewerid')) return;
  url.searchParams.set('viewerid', `qp-guest-${crypto.randomUUID()}`);
  window.history.replaceState(null, document.title, `${url.pathname}${url.search}${url.hash}`);
}

/**
 * 返回 true 表示本页已经被重定向到加入表单，不要再挂载播放器。
 */
export async function prepareWatchTab(): Promise<boolean> {
  const credentials = questionPulseCredentials;
  if (!credentials) {
    // 没有本课堂的 token，就不能拿 URL 里遗留的 viewer id 继续播放。
    stripStaleViewerIdentity();
    ensureVisitorViewerId();
    return false;
  }
  if (window.self !== window.top) return false;
  if (typeof BroadcastChannel === 'undefined') return false;

  const selfId = currentTabId();
  const participantId = credentials.participantId;
  let channel: BroadcastChannel;
  try {
    channel = new BroadcastChannel(`questionpulse.tab.${credentials.sessionId}`);
  } catch {
    return false;
  }

  const peers = new Set<string>();
  channel.onmessage = (event: MessageEvent<TabMessage>) => {
    const data = event.data;
    if (!data || data.tabId === selfId) return;
    if (data.participantId !== participantId) return;
    peers.add(data.tabId);
    if (data.type === 'probe') {
      const answer: TabMessage = { type: 'alive', tabId: selfId, participantId };
      channel.postMessage(answer);
    }
  };
  const probe: TabMessage = { type: 'probe', tabId: selfId, participantId };
  channel.postMessage(probe);

  await new Promise(resolve => window.setTimeout(resolve, PROBE_TIMEOUT_MS));

  if (peers.size === 0) {
    window.__questionPulseTabChannels = [...(window.__questionPulseTabChannels || []), channel];
    return false;
  }

  channel.close();
  clearQuestionPulseCredentials();
  window.location.replace(questionPulseJoinUrl(true));
  return true;
}
