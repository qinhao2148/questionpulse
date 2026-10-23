(() => {
  const HOST_ID = 'questionpulse-copilot-host'
  if (document.getElementById(HOST_ID)) return

  const host = document.createElement('div')
  host.id = HOST_ID
  host.style.position = 'fixed'
  host.style.right = '24px'
  host.style.bottom = '24px'
  host.style.zIndex = '2147483647'
  document.documentElement.appendChild(host)

  const root = host.attachShadow({ mode: 'closed' })
  root.innerHTML = `
    <style>
      :host { all: initial; }
      * { box-sizing: border-box; }
      button, input { font: inherit; }
      .qp-orb { width: 58px; height: 58px; border: 1px solid #b99cff88; border-radius: 50%; color: white; cursor: grab; touch-action: none; background: radial-gradient(circle at 35% 30%, #cdb6ff 0 8%, #8657e8 28%, #2b1749 72%); box-shadow: 0 10px 35px #6d35d988, inset 0 0 18px #e1d4ff44; position: relative; display: grid; place-items: center; }
      .qp-orb.qp-disconnected { filter: grayscale(1); opacity: .72; box-shadow: 0 8px 24px #0008; }
      .qp-orb.qp-disconnected::after { animation: none; border-color: #a9a1af55; }
      .qp-orb::after { content: ''; width: 72px; height: 72px; position: absolute; border-radius: 50%; border: 1px solid #a77cff55; animation: qp-pulse 2.4s ease-out infinite; }
      .qp-orb span { font: 700 16px/1 system-ui, sans-serif; }
      .qp-count { position: absolute; right: -3px; top: -5px; min-width: 21px; height: 21px; padding: 0 5px; border-radius: 11px; background: #ff4d78; display: grid; place-items: center; font: 700 11px/1 system-ui, sans-serif; }
      .qp-panel { width: min(390px, calc(100vw - 32px)); max-height: min(690px, calc(100vh - 32px)); overflow: auto; border: 1px solid #ffffff1f; border-radius: 20px; color: #f7f2ff; background: linear-gradient(160deg, #181021 0%, #09070d 80%); box-shadow: 0 20px 70px #000a; font: 14px/1.45 Inter, system-ui, sans-serif; }
      .qp-hidden { display: none !important; }
      .qp-header { position: sticky; top: 0; z-index: 2; padding: 18px 18px 14px; background: #130d1bdd; backdrop-filter: blur(14px); border-bottom: 1px solid #ffffff12; display: flex; justify-content: space-between; gap: 12px; align-items: center; cursor: grab; touch-action: none; }
      .qp-brand { display: flex; gap: 10px; align-items: center; }
      .qp-brand small { display: block; max-width: 195px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      .qp-mini-orb { width: 30px; height: 30px; border-radius: 50%; background: radial-gradient(circle at 35% 30%, #d7c7ff, #7f4bd8 40%, #27143f 80%); box-shadow: 0 0 20px #8d5de977; }
      .qp-header strong, .qp-card strong { display: block; }
      .qp-header small, .qp-muted { color: #a89db2; font-size: 12px; }
      .qp-icon { border: 0; background: transparent; color: #cabbe0; cursor: pointer; font-size: 20px; }
      .qp-body { padding: 16px; display: grid; gap: 12px; }
      .qp-card { border: 1px solid #ffffff14; border-radius: 15px; background: #ffffff08; padding: 14px; }
      .qp-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
      .qp-eyebrow { color: #aa7cff; font-size: 10px; font-weight: 800; letter-spacing: .14em; margin-bottom: 5px; }
      .qp-status { display: inline-flex; align-items: center; gap: 6px; color: #b9edcf; font-size: 12px; }
      .qp-status::before { content: ''; width: 7px; height: 7px; border-radius: 50%; background: #57d99a; box-shadow: 0 0 12px #57d99a; }
      .qp-list { display: grid; gap: 9px; margin-top: 10px; }
      .qp-rooms { display: grid; gap: 8px; margin-top: 10px; }
      .qp-room { display: grid; gap: 3px; width: 100%; text-align: left; border: 1px solid #ffffff14; border-radius: 11px; padding: 10px 11px; background: #0d0912; color: inherit; cursor: pointer; font: inherit; }
      .qp-room:hover { border-color: #9f77ec66; background: #17101f; }
      .qp-room[disabled] { border-color: #57d99a55; cursor: default; }
      .qp-room b { font-size: 13px; }
      .qp-room span { color: #a89db2; font-size: 12px; }
      .qp-cluster { border: 1px solid #ffffff12; border-radius: 12px; padding: 11px; background: #0d0912; }
      .qp-title { font-weight: 700; margin: 3px 0 7px; }
      .qp-meta { color: #a89db2; font-size: 12px; }
      .qp-ai { margin-top: 8px; padding: 8px 9px; border-radius: 9px; color: #ddcff7; background: #9f77ec14; font-size: 12px; }
      .qp-ai small { display: block; margin-top: 4px; color: #a89db2; line-height: 1.45; }
      .qp-actions { display: flex; gap: 7px; flex-wrap: wrap; margin-top: 10px; }
      .qp-button { border: 1px solid #9f77ec66; border-radius: 9px; background: #6f41bd33; color: #efe7ff; cursor: pointer; padding: 7px 10px; font-size: 12px; }
      .qp-button.primary { border-color: #9e72ff; background: #8254de; }
      .qp-button:disabled { opacity: .5; cursor: wait; }
      .qp-form { display: grid; gap: 9px; }
      .qp-form label { display: grid; gap: 4px; color: #cfc4d9; font-size: 12px; }
      .qp-form input { width: 100%; border: 1px solid #ffffff1f; border-radius: 9px; background: #08060b; color: white; padding: 9px 10px; }
      .qp-error { color: #ff94ab; font-size: 12px; white-space: pre-wrap; }
      .qp-empty { color: #a89db2; text-align: center; padding: 16px 4px; }
      .qp-status.qp-ended { color: #a89db2; }
      .qp-status.qp-ended::before { background: #7c7385; box-shadow: none; }
      .qp-links { display: flex; gap: 7px; align-items: center; }
      a.qp-button { text-decoration: none; display: inline-flex; align-items: center; }
      .qp-note { color: #e2c98d; font-size: 12px; margin-top: 8px; }
      @keyframes qp-pulse { 0% { transform: scale(.72); opacity: .85; } 75%,100% { transform: scale(1.25); opacity: 0; } }
      @media (prefers-reduced-motion: reduce) { .qp-orb::after { animation: none; } }
    </style>
    <button class="qp-orb" id="qp-orb" aria-label="打开 QuestionPulse 教师助手"><span>QP</span><b class="qp-count qp-hidden" id="qp-count">0</b></button>
    <section class="qp-panel qp-hidden" id="qp-panel" aria-label="QuestionPulse 教师助手">
      <header class="qp-header">
        <div class="qp-brand"><i class="qp-mini-orb"></i><div><strong>QuestionPulse</strong><small>Teacher Copilot</small></div></div>
        <button class="qp-icon" id="qp-close" aria-label="收起助手">×</button>
      </header>
      <main class="qp-body" id="qp-body"></main>
    </section>
  `

  const orb = root.getElementById('qp-orb')
  const panel = root.getElementById('qp-panel')
  const close = root.getElementById('qp-close')
  const body = root.getElementById('qp-body')
  const count = root.getElementById('qp-count')
  let timer
  let busy = false
  let snapshot = null
  let checks = []
  let suppressOpen = false
  let showAllClusters = false
  let settingsCache = null
  let lastRenderKey = ''
  let followAttempted = false
  let followedTitle = ''
  let followNoticeShown = false
  let pickerRooms = null
  let syncNote = ''
  // Auto-pull chat history only once per classroom: POLYV rate-limits the
  // history API and the teacher may still be typing before the lesson starts.
  const autoSyncedSessions = new Set()
  let loginWatch

  function stopPolling() {
    clearInterval(timer)
    timer = undefined
    clearTimeout(settleTimer)
    settleTimer = undefined
  }

  function startPolling() {
    stopPolling()
    if (snapshot?.status === 'ended') return
    // 面板收起时也要继续刷新，否则右上角的未处理数量会停在打开时的旧值。
    // 展开时 3 秒一次，收起时 10 秒一次，避免无谓的请求。
    const cadence = panel.classList.contains('qp-hidden') ? 10000 : 3000
    timer = setInterval(() => {
      // Pull first, then read the snapshot. Running them side by side made every
      // sync useless for the current tick: the snapshot came back before the new
      // message was even stored.
      if (polling) return
      polling = true
      void (async () => {
        try {
          const pulled = await autoSyncChat()
          await refresh()
          if (!pulled) return
          // Classification only starts after the response, so look again once the
          // model has had time to finish rather than waiting for the next tick.
          clearTimeout(settleTimer)
          settleTimer = setTimeout(() => {
            if (!document.hidden && !busy) void refresh()
          }, SETTLE_REFRESH_MS)
        } finally {
          polling = false
        }
      })()
    }, cadence)
  }

  // POLYV only exposes chat history through a pull API: nothing pushes a
  // learner's message to us. Without this the panel stays empty until the
  // teacher presses 同步聊天, which is exactly what looked like "no records".
  // 6s is a compromise: a pull costs ~300ms and DeepSeek takes ~1.8s, so any
  // shorter starts running into POLYV's rate limits for no visible gain.
  const AUTO_SYNC_INTERVAL_MS = 6000
  const SETTLE_REFRESH_MS = 2500
  let lastAutoSyncAt = 0
  let polling = false
  let settleTimer

  async function autoSyncChat() {
    if (busy || document.hidden || !snapshot || snapshot.status === 'ended') return false
    // Stamp before the request: a failing endpoint must not be retried on
    // every 3-second tick.
    if (Date.now() - lastAutoSyncAt < AUTO_SYNC_INTERVAL_MS) return false
    lastAutoSyncAt = Date.now()
    try {
      const settings = await config()
      if (!settings.sessionId) return false
      const result = await api(
        `/sessions/${settings.sessionId}/integrations/polyv/chat/sync`,
        { method: 'POST', body: '{}' },
      )
      const data = result?.data || result || {}
      if ((data.accepted ?? 0) > 0) {
        syncNote = `自动同步：新增 ${data.accepted} 条，正在识别疑问…`
        return true
      }
      return false
    } catch {
      // The manual button reports the reason; the background pull stays quiet
      // so a broken POLYV credential does not spam the floating panel.
      return false
    }
  }

  // After a re-login the extension picks up the new token on its own. Keep
  // retrying quietly so the panel heals without the teacher pressing anything.
  function startLoginWatch() {
    if (loginWatch) return
    loginWatch = setInterval(() => {
      if (panel.classList.contains('qp-hidden') || document.hidden) return
      refresh()
    }, 4000)
  }

  function stopLoginWatch() {
    clearInterval(loginWatch)
    loginWatch = undefined
  }

  function setConnectionState(connected) {
    orb.classList.toggle('qp-disconnected', !connected)
    orb.setAttribute('aria-label', connected ? '打开 QuestionPulse 教师助手' : 'QuestionPulse 已断开，点击重新连接')
  }

  function keepInsideViewport() {
    const rect = host.getBoundingClientRect()
    const left = Math.max(8, Math.min(window.innerWidth - rect.width - 8, rect.left))
    const top = Math.max(8, Math.min(window.innerHeight - rect.height - 8, rect.top))
    host.style.right = 'auto'
    host.style.bottom = 'auto'
    host.style.left = `${left}px`
    host.style.top = `${top}px`
  }

  function enableDrag(handle) {
    let origin = null
    handle.addEventListener('pointerdown', (event) => {
      if (event.button !== 0 || event.target.closest('#qp-close')) return
      const rect = host.getBoundingClientRect()
      origin = { x: event.clientX, y: event.clientY, left: rect.left, top: rect.top, moved: false }
      handle.setPointerCapture(event.pointerId)
    })
    handle.addEventListener('pointermove', (event) => {
      if (!origin || !handle.hasPointerCapture(event.pointerId)) return
      const dx = event.clientX - origin.x
      const dy = event.clientY - origin.y
      if (Math.abs(dx) + Math.abs(dy) > 5) origin.moved = true
      const rect = host.getBoundingClientRect()
      const left = Math.max(8, Math.min(window.innerWidth - rect.width - 8, origin.left + dx))
      const top = Math.max(8, Math.min(window.innerHeight - rect.height - 8, origin.top + dy))
      host.style.right = 'auto'
      host.style.bottom = 'auto'
      host.style.left = `${left}px`
      host.style.top = `${top}px`
    })
    handle.addEventListener('pointerup', (event) => {
      if (!origin) return
      suppressOpen = suppressOpen || origin.moved
      origin = null
      handle.releasePointerCapture(event.pointerId)
    })
    handle.addEventListener('pointercancel', () => { origin = null })
  }

  const storageGet = (keys) => new Promise((resolve, reject) => {
    try {
      chrome.storage.session.get(keys, (value) => {
        if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message))
        else resolve(value)
      })
    } catch (error) {
      reject(error)
    }
  })
  const storageSet = (value) => new Promise((resolve, reject) => {
    try {
      chrome.storage.session.set(value, () => {
        if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message))
        else resolve()
      })
    } catch (error) {
      reject(error)
    }
  })
  const escapeHtml = (value = '') => String(value).replace(/[&<>'"]/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' })[character])

  async function config() {
    const saved = await storageGet(['apiBaseUrl', 'webBaseUrl', 'sessionId', 'teacherToken'])
    const apiBaseUrl = saved.apiBaseUrl || 'http://127.0.0.1:8000/api/v1'
    return {
      apiBaseUrl,
      webBaseUrl: saved.webBaseUrl
        || apiBaseUrl.replace(/\/api\/v1\/?$/, '').replace(/:8000$/, ':5173'),
      sessionId: saved.sessionId || '',
      teacherToken: saved.teacherToken || '',
    }
  }

  async function api(path, init = {}) {
    const result = await new Promise((resolve, reject) => {
      chrome.runtime.sendMessage(
        { type: 'questionpulse-api', path, init: { method: init.method, body: init.body } },
        (response) => {
          if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message))
          else resolve(response)
        },
      )
    })
    if (!result?.ok) throw new Error(result?.error || 'extension_request_failed')
    return result.data
  }

  function nextAction(cluster) {
    const states = {
      open: ['addressing', '开始讲解'],
      addressing: ['awaiting_feedback', '结束讲解'],
      awaiting_feedback: ['closed', '关闭疑问'],
      closed: ['open', '重新打开'],
    }
    return states[cluster.status] || null
  }

  function teacherUrl() {
    const base = settingsCache?.webBaseUrl || 'http://127.0.0.1:5173'
    // 教师端已收敛为单页，课堂在页面内切换，用 ?session= 才能直接落到这堂课。
    const sessionId = settingsCache?.sessionId || ''
    return sessionId ? `${base}/?session=${encodeURIComponent(sessionId)}` : `${base}/`
  }

  function teacherHomeUrl() {
    return settingsCache?.webBaseUrl || 'http://127.0.0.1:5173'
  }

  function pageChannelId() {
    const fromPath = location.pathname.match(/\/(?:watch|live|channel)\/(\d{5,})/i)
    if (fromPath) return fromPath[1]
    const fromQuery = location.search.match(/[?&](?:channelId|channel_id|channel)=(\d{5,})/i)
    return fromQuery ? fromQuery[1] : ''
  }

  function ongoingRooms(rooms) {
    return (rooms || []).filter((room) => room.status !== 'ended')
  }

  function pickLiveClassroom(rooms, channel) {
    const live = ongoingRooms(rooms)
    if (!live.length) return null
    const channelId = channel || pageChannelId()
    const sameChannel = channelId ? live.find((room) => room.polyv_channel_id === channelId) : null
    if (sameChannel) return sameChannel
    // Only guess when there is exactly one unended classroom. With several, let
    // the teacher pick instead of silently showing a class they are not teaching.
    return live.length === 1 ? live[0] : null
  }

  function roomRow(room, currentId) {
    const current = room.id === currentId
    const created = room.created_at
      ? new Date(room.created_at).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })
      : ''
    return `<button class="qp-room" data-adopt="${escapeHtml(room.id)}"${current ? ' disabled' : ''}>
      <b>${escapeHtml(room.title)}${current ? '（当前）' : ''}</b>
      <span>${room.join_code ? `加入码 ${escapeHtml(room.join_code)} · ` : ''}${room.question_count} 条疑问${created ? ` · ${escapeHtml(created)} 创建` : ''}</span>
    </button>`
  }

  function bindRoomRows() {
    root.querySelectorAll('[data-adopt]').forEach((button) => button.addEventListener('click', adoptFromPicker))
  }

  async function openRoomPicker(rooms, message = '') {
    stopPolling()
    if (!rooms) {
      // 每次都重新拉一遍，别复用上一次选择器留下的列表。
      try {
        rooms = await api('/teacher/sessions')
      } catch (error) {
        pickerRooms = null
        renderError(error)
        return
      }
    }
    pickerRooms = rooms
    renderRoomPicker(message)
  }

  function renderRoomPicker(message = '') {
    stopPolling()
    lastRenderKey = ''
    const rooms = ongoingRooms(pickerRooms)
    const currentId = settingsCache?.sessionId || ''
    const subtitle = root.querySelector('.qp-brand small')
    if (subtitle) subtitle.textContent = '选择要连接的课堂'
    body.innerHTML = `
      <section class="qp-card">
        <div class="qp-eyebrow">ONGOING CLASSROOMS</div><strong>进行中的课堂</strong>
        <p class="qp-muted">选一堂，之后面板上的操作都作用到这堂课。切换会先确认一次，因为绑错课堂会改到别的班的疑问和检测。</p>
        ${message ? `<div class="qp-note">${escapeHtml(message)}</div>` : ''}
        ${rooms.length ? `<div class="qp-rooms">${rooms.map((room) => roomRow(room, currentId)).join('')}</div>` : '<div class="qp-empty">还没有未结束的课堂，先去教师端创建一堂。</div>'}
        <div class="qp-actions" style="margin-top:10px">
          ${currentId ? '<button class="qp-button" id="qp-picker-cancel">返回</button>' : ''}
          <a class="qp-button" href="${teacherHomeUrl()}" target="_blank" rel="noopener">教师课堂中心</a>
        </div>
      </section>`
    bindRoomRows()
    root.getElementById('qp-picker-cancel')?.addEventListener('click', () => {
      pickerRooms = null
      lastRenderKey = ''
      refresh()
    })
  }

  async function adoptFromPicker(event) {
    const id = event.currentTarget.dataset.adopt
    const room = ongoingRooms(pickerRooms).find((item) => item.id === id)
    if (!room || id === settingsCache?.sessionId) return
    if (!window.confirm(`切换到《${room.title}》？\n${room.join_code ? `加入码 ${room.join_code}\n` : ''}之后面板上的操作都会作用到这堂课。`)) return
    pickerRooms = null
    await adoptClassroom(room)
    // 手动切换不是「上一堂课结束后自动跟随」，别把那条提示也点亮。
    followedTitle = ''
    followNoticeShown = true
    followAttempted = true
    await refresh()
  }

  async function adoptClassroom(target) {
    followedTitle = target.title || ''
    settingsCache = { ...(settingsCache || {}), sessionId: target.id }
    showAllClusters = false
    await storageSet({ sessionId: target.id })
  }

  function renderArchived() {
    const clusters = snapshot?.clusters || []
    count.classList.add('qp-hidden')
    body.innerHTML = `
      <section class="qp-card">
        <div class="qp-row"><div><div class="qp-eyebrow">CLASSROOM ARCHIVED</div><strong>${escapeHtml(snapshot.title)}</strong></div><span class="qp-status qp-ended">已结束</span></div>
        <div class="qp-meta">课堂已归档。${clusters.length} 个疑问主题停留在结束时刻，不再接收新问题。</div>
      </section>
      <section class="qp-card">
        <div class="qp-eyebrow">STILL SHOWING THE LAST CLASS?</div>
        <strong>助手还连着上一堂课</strong>
        <p class="qp-muted">切到当前正在进行中的课堂，这里会重新加载实时疑问。教师令牌不需要重新输入。</p>
        <div class="qp-actions">
          <button class="qp-button primary" id="qp-switch">选择进行中的课堂</button>
          <a class="qp-button" href="${teacherUrl()}" target="_blank" rel="noopener">在教师后台查看报告</a>
        </div>
        <div class="qp-note qp-hidden" id="qp-switch-note"></div>
      </section>
      <section class="qp-card"><div class="qp-row"><span class="qp-muted">需要新建课堂或查看全部记录？</span><a class="qp-button" href="${teacherHomeUrl()}" target="_blank" rel="noopener">打开教师课堂中心</a></div></section>
    `
    root.getElementById('qp-switch')?.addEventListener('click', switchClassroom)
  }

  async function switchClassroom(event) {
    const button = event.currentTarget
    const note = root.getElementById('qp-switch-note')
    button.disabled = true
    try {
      const rooms = await api('/teacher/sessions')
      const live = ongoingRooms(rooms)
      if (!live.length) {
        if (note) {
          note.classList.remove('qp-hidden')
          note.textContent = '当前没有进行中的课堂。请先在教师端创建并开始一堂课。'
        }
        return
      }
      if (live.length > 1) {
        // 多堂课同时在跑的时候让老师自己选，猜错就是改到别人的课堂。
        await openRoomPicker(live, '有不止一堂课还没结束，选一堂继续。')
        return
      }
      await adoptClassroom(live[0])
      followedTitle = ''
      followAttempted = true
      followNoticeShown = false
      await refresh()
    } catch (error) {
      renderError(error)
    } finally {
      button.disabled = false
    }
  }

  async function endClassroom(event) {
    const button = event.currentTarget
    if (!window.confirm('确定结束这堂课吗？结束后学生无法继续提问，当前疑问会归档。')) return
    button.disabled = true
    try {
      const settings = await config()
      await api(`/sessions/${settings.sessionId}/end`, { method: 'POST', body: '{}' })
      await refresh()
    } catch (error) {
      renderError(error)
    } finally {
      button.disabled = false
    }
  }

  function renderKey() {
    const clusters = snapshot?.clusters || []
    return JSON.stringify({
      title: snapshot?.title,
      status: snapshot?.status,
      joinCode: snapshot?.join_code || '',
      pending: snapshot?.pending_questions?.length || 0,
      all: showAllClusters,
      followed: followedTitle,
      note: syncNote,
      clusters: clusters.map((item) => [
        item.id, item.status, item.version, item.question_count,
        item.participant_count, item.confusion_score, item.feedback?.still_confused,
      ]),
      checks: (checks || []).map((item) => [
        item.id, item.status, item.response_count, item.correct_count,
      ]),
    })
  }

  function renderSnapshot() {
    stopLoginWatch()
    setConnectionState(true)
    const subtitle = root.querySelector('.qp-brand small')
    if (subtitle) subtitle.textContent = snapshot?.title ? `当前课堂：${snapshot.title}` : 'Teacher Copilot'
    // 原来每 3 秒整体重建面板，滚动位置和刚点下去的按钮状态都会被冲掉。
    // 数据没变化时直接复用现有 DOM。
    const key = renderKey()
    if (key === lastRenderKey && body.childElementCount) return
    lastRenderKey = key
    if (snapshot?.status === 'ended') {
      clearInterval(timer)
      renderArchived()
      return
    }
    const clusters = snapshot?.clusters || []
    const openClusters = clusters.filter((item) => item.status !== 'closed')
    const priorityClusters = [...openClusters].sort((a, b) => b.confusion_score - a.confusion_score)
    const visibleClusters = showAllClusters ? priorityClusters : priorityClusters.slice(0, 3)
    count.textContent = String(openClusters.length)
    count.classList.toggle('qp-hidden', openClusters.length === 0)
    body.innerHTML = `
      ${followedTitle && !followNoticeShown ? `<section class="qp-card"><div class="qp-eyebrow">AUTO SWITCHED</div><div class="qp-meta">上一堂课《${escapeHtml(followedTitle)}》已结束，助手已自动切到当前课堂。</div></section>` : ''}
      <section class="qp-card">
        <div class="qp-row"><div><div class="qp-eyebrow">LIVE CLASSROOM</div><strong>${escapeHtml(snapshot.title)}</strong></div><span class="qp-status">${snapshot.status === 'ended' ? '已归档' : '已连接'}</span></div>
        <div class="qp-meta">${clusters.length} 个疑问簇 · ${snapshot.pending_questions.length} 条待处理${snapshot.join_code ? ` · 加入码 <b>${escapeHtml(snapshot.join_code)}</b>` : ''}</div>
        <div class="qp-actions"><button class="qp-button" id="qp-picker">切换课堂</button></div>
      </section>
      <section class="qp-card">
        <div class="qp-eyebrow">QUESTION PRIORITY</div><strong>当前高优先级疑问</strong>
        <div class="qp-list">
          ${visibleClusters.map((cluster) => {
            const action = nextAction(cluster)
            const check = checks.find((item) => item.cluster_id === cluster.id
              && item.feedback_round === cluster.feedback_round)
            return `<article class="qp-cluster">
              <div class="qp-row"><span class="qp-meta">${escapeHtml(cluster.status)}</span><span class="qp-meta">${cluster.participant_count} 人 · ${cluster.question_count} 条</span></div>
              <div class="qp-title">${escapeHtml(cluster.title)}</div>
              <div class="qp-meta">困惑指数 ${cluster.confusion_score} · 仍困惑 ${cluster.feedback.still_confused} 人</div>
              ${cluster.ai_normalized_intent ? `<div class="qp-ai"><b>AI 识别：</b>${escapeHtml(cluster.ai_normalized_intent)}${cluster.ai_semantic_reason ? `<small>${escapeHtml(cluster.ai_semantic_reason)}</small>` : ''}</div>` : ''}
              ${snapshot.status !== 'ended' && action ? `<div class="qp-actions"><button class="qp-button primary" data-cluster="${cluster.id}" data-version="${cluster.version}" data-status="${action[0]}">${action[1]}</button></div>` : ''}
              ${check ? `<div class="qp-meta">理解检测：${escapeHtml(check.status)} · ${check.response_count}/${check.target_count} 已答 · ${check.correct_count} 人正确</div>` : ''}
              ${snapshot.status !== 'ended' && cluster.status === 'awaiting_feedback' && !check ? `<div class="qp-actions"><button class="qp-button" data-generate-check="${cluster.id}">生成检测草稿</button></div>` : ''}
              ${snapshot.status !== 'ended' && check?.status === 'draft' ? `<div class="qp-actions"><button class="qp-button" data-approve-check="${check.id}">审核并发布检测</button></div>` : ''}
              ${snapshot.status !== 'ended' && check?.status === 'active' ? `<div class="qp-actions"><button class="qp-button" data-close-check="${check.id}">结束检测</button></div>` : ''}
            </article>`
          }).join('') || `<div class="qp-empty">暂时没有课堂疑问${snapshot.status === 'ended' ? '' : '<br><span class="qp-muted">学生在保利威聊天框里的提问不会自动推送，点下方「同步聊天」拉取</span>'}</div>`}
        </div>
        ${priorityClusters.length > 3 ? `<div class="qp-actions"><button class="qp-button" id="qp-toggle-clusters">${showAllClusters ? '仅看 Top 3' : `查看全部 ${priorityClusters.length} 个待处理疑问`}</button></div>` : ''}
      </section>
      <section class="qp-card">
        <div class="qp-row"><span class="qp-muted">完整配置、原始问题和报告请在教师后台查看。</span><div class="qp-links"><a class="qp-button" href="${teacherUrl()}" target="_blank" rel="noopener">打开教师端</a><button class="qp-button" id="qp-sync">同步聊天</button><button class="qp-button" id="qp-refresh">刷新</button></div></div>
        ${syncNote ? `<div class="qp-note">${escapeHtml(syncNote)}</div>` : ''}
        <div class="qp-meta" style="margin-top:10px">直播已经结束？结束这堂课会归档当前疑问，助手不再显示它。</div>
        <div class="qp-actions"><button class="qp-button" id="qp-end">结束这堂课</button></div>
      </section>
    `
    if (followedTitle) followNoticeShown = true
    root.getElementById('qp-refresh')?.addEventListener('click', refresh)
    root.getElementById('qp-sync')?.addEventListener('click', syncChatClick)
    root.getElementById('qp-picker')?.addEventListener('click', () => openRoomPicker())
    root.getElementById('qp-end')?.addEventListener('click', endClassroom)
    root.getElementById('qp-toggle-clusters')?.addEventListener('click', () => {
      showAllClusters = !showAllClusters
      renderSnapshot()
    })
    root.querySelectorAll('[data-cluster]').forEach((button) => button.addEventListener('click', changeStatus))
    root.querySelectorAll('[data-generate-check]').forEach((button) => button.addEventListener('click', generateCheck))
    root.querySelectorAll('[data-approve-check]').forEach((button) => button.addEventListener('click', approveCheck))
    root.querySelectorAll('[data-close-check]').forEach((button) => button.addEventListener('click', closeCheck))
  }

  async function renderSetup(message = '', presetSessionId = '') {
    stopPolling()
    stopLoginWatch()
    setConnectionState(false)
    lastRenderKey = ''
    let saved = {}
    try {
      saved = await storageGet(['apiBaseUrl', 'sessionId', 'teacherToken'])
    } catch {
      saved = {}
    }
    const apiBaseUrl = saved.apiBaseUrl || 'http://127.0.0.1:8000/api/v1'
    const sessionId = presetSessionId || saved.sessionId || ''
    body.innerHTML = `
      <section class="qp-card">
        <div class="qp-eyebrow">CONNECT CLASSROOM</div><strong>连接 QuestionPulse 课堂</strong>
        <p class="qp-muted">凭据只保存在浏览器扩展本地，不会发送给 POLYV 页面。教师端登录后可在浏览器控制台执行 <code>localStorage['questionpulse.teacher_portal_token']</code> 取到令牌。</p>
        <form class="qp-form" id="qp-form">
          <label>后端地址<input name="apiBaseUrl" value="${escapeHtml(apiBaseUrl)}" required /></label>
          <label>课堂 ID<input name="sessionId" value="${escapeHtml(sessionId)}" autocomplete="off" required /></label>
          <label>教师访问令牌<input name="teacherToken" type="password" autocomplete="off" placeholder="qpa_..." required /></label>
          <button class="qp-button primary" type="submit">保存并连接</button>
          ${message ? `<div class="qp-error">${escapeHtml(message)}</div>` : ''}
        </form>
      </section>
      <div id="qp-setup-rooms"></div>`
    root.getElementById('qp-form').addEventListener('submit', saveSetup)
    if (saved.teacherToken) await fillSetupRooms()
  }

  // 已经有令牌的情况下，让老师直接点列表里的课堂，省掉手抄课堂 ID 那一步。
  async function fillSetupRooms() {
    const slot = root.getElementById('qp-setup-rooms')
    if (!slot) return
    try {
      const rooms = ongoingRooms(await api('/teacher/sessions'))
      if (!rooms.length || !root.getElementById('qp-setup-rooms')) return
      pickerRooms = rooms
      slot.innerHTML = `<section class="qp-card"><div class="qp-eyebrow">ONGOING CLASSROOMS</div><strong>从进行中的课堂里选</strong><div class="qp-rooms">${rooms.map((room) => roomRow(room, '')).join('')}</div></section>`
      bindRoomRows()
    } catch {
      // 列表只是省打字，拉不到就保留手动表单。
    }
  }

  async function saveSetup(event) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    try {
      await storageSet({
        apiBaseUrl: String(data.get('apiBaseUrl')).replace(/\/$/, ''),
        sessionId: String(data.get('sessionId')).trim(),
        teacherToken: String(data.get('teacherToken')).trim(),
      })
      await refresh()
    } catch (error) {
      renderError(error)
    }
  }

  async function changeStatus(event) {
    if (busy) return
    busy = true
    const button = event.currentTarget
    button.disabled = true
    try {
      const settings = await config()
      await api(`/sessions/${settings.sessionId}/clusters/${button.dataset.cluster}/status`, {
        method: 'PATCH',
        body: JSON.stringify({ status: button.dataset.status, expected_version: Number(button.dataset.version) }),
      })
      await refresh()
    } catch (error) {
      renderError(error)
    } finally {
      busy = false
    }
  }

  async function syncChat(button) {
    if (busy) return
    busy = true
    if (button) {
      button.disabled = true
      button.textContent = '同步中…'
    }
    try {
      const settings = await config()
      if (!settings.sessionId) return
      const result = await api(
        `/sessions/${settings.sessionId}/integrations/polyv/chat/sync`,
        { method: 'POST', body: '{}' },
      )
      const data = result?.data || result || {}
      const fetched = data.fetched ?? 0
      const accepted = data.accepted ?? 0
      const duplicates = data.duplicates ?? 0
      syncNote = accepted
        ? `已拉取 ${fetched} 条，新增 ${accepted} 条（去重 ${duplicates} 条），正在识别疑问…`
        : `已拉取 ${fetched} 条，没有新消息（去重 ${duplicates} 条）`
    } catch (error) {
      syncNote = error instanceof Error ? `同步失败：${error.message}` : '同步失败'
    } finally {
      busy = false
      if (button) {
        button.disabled = false
        button.textContent = '同步聊天'
      }
      lastAutoSyncAt = Date.now()
      await refresh()
      // The model starts only after the response, so the list needs one more
      // read a few seconds later to show the newly formed cluster.
      clearTimeout(settleTimer)
      settleTimer = setTimeout(() => {
        if (!document.hidden && !busy) void refresh()
      }, SETTLE_REFRESH_MS)
    }
  }

  function syncChatClick(event) {
    return syncChat(event.currentTarget)
  }

  async function checkAction(button, path) {
    if (busy) return
    busy = true
    button.disabled = true
    try {
      const settings = await config()
      await api(`/sessions/${settings.sessionId}${path}`, { method: 'POST', body: '{}' })
      await refresh()
    } catch (error) {
      renderError(error)
    } finally {
      busy = false
    }
  }

  function generateCheck(event) {
    return checkAction(event.currentTarget, `/clusters/${event.currentTarget.dataset.generateCheck}/checks/generate`)
  }

  function approveCheck(event) {
    return checkAction(event.currentTarget, `/checks/${event.currentTarget.dataset.approveCheck}/approve`)
  }

  function closeCheck(event) {
    return checkAction(event.currentTarget, `/checks/${event.currentTarget.dataset.closeCheck}/close`)
  }

  function renderError(error) {
    stopPolling()
    setConnectionState(false)
    lastRenderKey = ''
    const subtitle = root.querySelector('.qp-brand small')
    if (subtitle) subtitle.textContent = 'Teacher Copilot'
    const rawMessage = error instanceof Error ? error.message : '连接失败'
    const contextInvalidated = /extension context invalidated/i.test(rawMessage)
    const loginRequired = ['teacher_login_required', 'access_denied', 'access_expired'].includes(rawMessage)
    if (loginRequired) {
      startLoginWatch()
      const sessionId = settingsCache?.sessionId || ''
      body.innerHTML = `
        <section class="qp-card">
          <div class="qp-eyebrow">CONNECTION</div>
          <strong>教师登录已失效</strong>
          <p class="qp-muted">助手里存的令牌过期了，或者后端换过签名密钥。去教师端重新登录一次，助手会自动把新令牌同步过来，这个面板几秒内自己恢复，不用再点别的按钮。</p>
          <p class="qp-error">${escapeHtml(rawMessage)}</p>
          <div class="qp-actions">
            <a class="qp-button primary" href="${teacherHomeUrl()}" target="_blank" rel="noopener">去重新登录</a>
            <button class="qp-button" id="qp-retry">立即重试</button>
            <button class="qp-button" id="qp-manual">手动填令牌</button>
          </div>
          <div class="qp-note">已经登录过还是这样？打开教师端任意课堂页，等 3 秒让助手同步；仍不行就点「手动填令牌」直接粘贴。</div>
        </section>`
      root.getElementById('qp-retry').addEventListener('click', refresh)
      root.getElementById('qp-manual').addEventListener('click', () => renderSetup('', sessionId))
      return
    }
    stopLoginWatch()
    const message = contextInvalidated
      ? '扩展已重新加载，请刷新当前 POLYV 开播页面。'
      : rawMessage
    body.innerHTML = `<section class="qp-card"><div class="qp-eyebrow">CONNECTION</div><strong>助手暂时无法连接</strong><p class="qp-error">${escapeHtml(message)}</p><div class="qp-actions"><button class="qp-button primary" id="qp-retry">重新连接</button><button class="qp-button" id="qp-reset">重新配置</button></div></section>`
    root.getElementById('qp-retry').addEventListener('click', refresh)
    root.getElementById('qp-reset').addEventListener('click', () => renderSetup(message))
  }

  async function refresh() {
    try {
      const settings = await config()
      settingsCache = settings
      if (!settings.sessionId || !settings.teacherToken) {
        stopPolling()
        if (!root.getElementById('qp-form')) renderSetup()
        return
      }
      ;[snapshot, checks] = await Promise.all([
        api(`/sessions/${settings.sessionId}/teacher-snapshot`),
        api(`/sessions/${settings.sessionId}/checks`),
      ])
      if (snapshot?.status === 'ended' && !followAttempted) {
        followAttempted = true
        let target = null
        try {
          target = pickLiveClassroom(await api('/teacher/sessions'), snapshot.polyv_channel_id)
        } catch {
          // A stale token fails here. Fall through to the archived view; the
          // switch button will surface the actual reason when pressed.
          target = null
        }
        if (target && target.id !== settings.sessionId) {
          await adoptClassroom(target)
          return refresh()
        }
      }
      if (
        snapshot?.status !== 'ended'
        && !snapshot.last_synced_at
        && !autoSyncedSessions.has(settings.sessionId)
      ) {
        autoSyncedSessions.add(settings.sessionId)
        // A brand-new classroom has never pulled POLYV's chat history, so the
        // panel would look empty even after learners type. Pull once on first
        // open; later messages stay manual because the history API is rate
        // limited and polling it every few seconds is wasteful.
        void syncChat()
      }
      renderSnapshot()
      if (snapshot?.status === 'ended') stopPolling()
      else startPolling()
    } catch (error) {
      if (error instanceof Error && error.message === 'session_not_found') {
        await storageSet({ sessionId: '' })
        stopPolling()
        renderSetup('这堂课已被删除，请重新连接。')
        return
      }
      renderError(error)
    }
  }

  function openPanel() {
    orb.classList.add('qp-hidden')
    panel.classList.remove('qp-hidden')
    keepInsideViewport()
    stopPolling()
    refresh()
  }

  function closePanel() {
    panel.classList.add('qp-hidden')
    orb.classList.remove('qp-hidden')
    keepInsideViewport()
    startPolling()
  }

  enableDrag(orb)
  enableDrag(root.querySelector('.qp-header'))
  window.addEventListener('resize', keepInsideViewport)
  document.addEventListener('fullscreenchange', () => {
    const container = document.fullscreenElement || document.documentElement
    container.appendChild(host)
    keepInsideViewport()
  })
  orb.addEventListener('click', () => {
    if (suppressOpen) {
      suppressOpen = false
      return
    }
    openPanel()
  })
  close.addEventListener('click', closePanel)
  refresh()
})()
