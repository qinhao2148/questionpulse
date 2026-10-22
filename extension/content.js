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

  function stopPolling() {
    clearInterval(timer)
    timer = undefined
  }

  function startPolling() {
    stopPolling()
    if (!panel.classList.contains('qp-hidden')) timer = setInterval(refresh, 3000)
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
    const saved = await storageGet(['apiBaseUrl', 'sessionId', 'teacherToken'])
    return {
      apiBaseUrl: saved.apiBaseUrl || 'http://127.0.0.1:8000/api/v1',
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

  function renderSnapshot() {
    setConnectionState(true)
    if (snapshot?.status === 'ended') clearInterval(timer)
    const clusters = snapshot?.clusters || []
    const openClusters = clusters.filter((item) => item.status !== 'closed')
    const priorityClusters = [...clusters].sort((a, b) => b.confusion_score - a.confusion_score)
    count.textContent = String(openClusters.length)
    count.classList.toggle('qp-hidden', openClusters.length === 0)
    body.innerHTML = `
      <section class="qp-card">
        <div class="qp-row"><div><div class="qp-eyebrow">LIVE CLASSROOM</div><strong>${escapeHtml(snapshot.title)}</strong></div><span class="qp-status">${snapshot.status === 'ended' ? '已归档' : '已连接'}</span></div>
        <div class="qp-meta">${clusters.length} 个疑问簇 · ${snapshot.pending_questions.length} 条待处理</div>
      </section>
      <section class="qp-card">
        <div class="qp-eyebrow">QUESTION PRIORITY</div><strong>当前高优先级疑问</strong>
        <div class="qp-list">
          ${priorityClusters.slice(0, 3).map((cluster) => {
            const action = nextAction(cluster)
            const check = checks.find((item) => item.cluster_id === cluster.id)
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
          }).join('') || '<div class="qp-empty">暂时没有课堂疑问</div>'}
        </div>
      </section>
      <section class="qp-card"><div class="qp-row"><span class="qp-muted">完整配置、原始问题和报告请在教师后台查看。</span><button class="qp-button" id="qp-refresh">刷新</button></div></section>
    `
    root.getElementById('qp-refresh')?.addEventListener('click', refresh)
    root.querySelectorAll('[data-cluster]').forEach((button) => button.addEventListener('click', changeStatus))
    root.querySelectorAll('[data-generate-check]').forEach((button) => button.addEventListener('click', generateCheck))
    root.querySelectorAll('[data-approve-check]').forEach((button) => button.addEventListener('click', approveCheck))
    root.querySelectorAll('[data-close-check]').forEach((button) => button.addEventListener('click', closeCheck))
  }

  function renderSetup(message = '') {
    stopPolling()
    setConnectionState(false)
    body.innerHTML = `
      <section class="qp-card">
        <div class="qp-eyebrow">CONNECT CLASSROOM</div><strong>连接 QuestionPulse 课堂</strong>
        <p class="qp-muted">凭据只保存在浏览器扩展本地，不会发送给 POLYV 页面。</p>
        <form class="qp-form" id="qp-form">
          <label>后端地址<input name="apiBaseUrl" value="http://127.0.0.1:8000/api/v1" required /></label>
          <label>课堂 ID<input name="sessionId" autocomplete="off" required /></label>
          <label>教师访问令牌<input name="teacherToken" type="password" autocomplete="off" required /></label>
          <button class="qp-button primary" type="submit">保存并连接</button>
          ${message ? `<div class="qp-error">${escapeHtml(message)}</div>` : ''}
        </form>
      </section>`
    root.getElementById('qp-form').addEventListener('submit', saveSetup)
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
    const rawMessage = error instanceof Error ? error.message : '连接失败'
    const contextInvalidated = /extension context invalidated/i.test(rawMessage)
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
      if (!settings.sessionId || !settings.teacherToken) {
        stopPolling()
        if (!root.getElementById('qp-form')) renderSetup()
        return
      }
      ;[snapshot, checks] = await Promise.all([
        api(`/sessions/${settings.sessionId}/teacher-snapshot`),
        api(`/sessions/${settings.sessionId}/checks`),
      ])
      renderSnapshot()
      startPolling()
    } catch (error) {
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
    stopPolling()
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
