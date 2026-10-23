import {
  ChannelEvents,
  LiveStatus,
  PlayerEvents,
  createWatchCore,
  destroyWatchCore,
} from '@polyv/live-watch-sdk'
import type { ChannelEventsRelations, PlayerEventsRelations } from '@polyv/live-watch-sdk'

export type PolyvWatchStatus = 'idle' | 'loading' | 'ready' | 'playing' | 'waiting' | 'degraded' | 'ended'

export interface PolyvWatchCallbacks {
  onStatus?: (status: PolyvWatchStatus, detail: string) => void
}

let activeWatchCore: ReturnType<typeof createWatchCore> | null = null

function mapLiveStatus(status: LiveStatus): { status: PolyvWatchStatus; detail: string } {
  if (status === LiveStatus.Live) return { status: 'ready', detail: '直播流已就绪，正在开始播放' }
  if (status === LiveStatus.Playback) return { status: 'ended', detail: '直播已结束，回放正在生成' }
  if (status === LiveStatus.End) return { status: 'ended', detail: '主播已结束直播' }
  if (status === LiveStatus.Stop) return { status: 'waiting', detail: '直播暂时中断，等待主播恢复' }
  return { status: 'waiting', detail: '教师尚未开始直播，开播后画面会自动显示' }
}

export async function mountPolyvWatch(
  container: HTMLDivElement,
  channelId: string,
  viewerId: string,
  callbacks: PolyvWatchCallbacks = {},
): Promise<void> {
  destroyWatchCore()
  container.replaceChildren()
  callbacks.onStatus?.('loading', `正在连接频道 ${channelId}`)
  const core = createWatchCore({
    channelId,
    userInfo: {
      userId: viewerId,
      nick: `QuestionPulse-${viewerId.slice(0, 8)}`,
      pic: 'https://livestatic.videocc.net/assets/wimages/missing_face.png',
    },
  })
  core.channel.eventEmitter.on(ChannelEvents.LiveStatusChange, ({ newLiveStatus, liveStatus }: ChannelEventsRelations[ChannelEvents.LiveStatusChange]) => {
    const next = mapLiveStatus(newLiveStatus || liveStatus)
    callbacks.onStatus?.(next.status, next.detail)
    if (next.status === 'ready' && core.player.supportRefresh().support) core.player.refresh()
  })
  core.player.eventEmitter.on(PlayerEvents.PlayerPlaying, () => {
    callbacks.onStatus?.('playing', '直播播放正常')
  })
  core.player.eventEmitter.on(PlayerEvents.PlayerPause, () => {
    if (core.channel.getLiveStatus() === LiveStatus.Live) {
      callbacks.onStatus?.('ready', '直播已就绪，点击播放器开始观看')
    }
  })
  core.player.eventEmitter.on(PlayerEvents.LivePlayerError, ({ errorCode }: PlayerEventsRelations[PlayerEvents.LivePlayerError]) => {
    callbacks.onStatus?.('degraded', `暂时无法播放直播${errorCode ? `（${errorCode}）` : ''}`)
  })
  await core.setup()
  if (!core.auth.isAuthorized()) {
    const authResult = await core.auth.verifyNoneAuth()
    if (!authResult.success) {
      throw new Error(authResult.failMessage || `POLYV 观看授权失败：${authResult.failReason}`)
    }
  }
  await core.connect()
  const initial = mapLiveStatus(core.channel.getLiveStatus())
  callbacks.onStatus?.(initial.status, initial.detail)
  await core.player.setupPlayer({ container, autoplay: false, lowLatency: false })
  await core.interactReceive.setupIarCore()
  activeWatchCore = core
}

export function refreshPolyvWatch(): boolean {
  if (!activeWatchCore || !activeWatchCore.player.supportRefresh().support) return false
  activeWatchCore.player.refresh()
  return true
}

export async function sendPolyvQuestion(content: string): Promise<void> {
  if (!activeWatchCore) throw new Error('POLYV SDK 尚未连接')
  await activeWatchCore.ask.sendAskSpeak({ content })
}

export function unmountPolyvWatch(): void {
  activeWatchCore?.player.stop()
  activeWatchCore = null
  destroyWatchCore()
}
