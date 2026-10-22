import { QuestionAnswer, updateConfig } from '@polyv/interactions-receive-sdk'

export interface PolyvSdkConfig {
  channelId: string
  sessionId: string
  viewerId: string
  viewerNick: string
  socket: unknown
  getViewerApiToken: (callback: (value: { viewerApiToken: string }) => void) => Promise<void>
}

/**
 * Connects the official POLYV question/answer SDK after the live/chat SDK has
 * supplied its Socket.IO instance. Secrets and token signing stay on our backend.
 */
export function createPolyvQuestionAnswer(config: PolyvSdkConfig) {
  updateConfig({
    userInfo: { userId: config.viewerId, nick: config.viewerNick, pic: '' },
    channelInfo: {
      channelId: config.channelId,
      roomId: config.channelId,
      sessionId: config.sessionId,
    },
    socket: config.socket,
    getViewerApiToken: config.getViewerApiToken,
  } as Parameters<typeof updateConfig>[0])
  return new QuestionAnswer()
}

export const polyvSdkVersion = '0.24.0'
