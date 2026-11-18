import { useCallback, useEffect, useRef, useState } from 'react'
import type { Control, Inspection, ProcessStatus, Settings } from '../contract'
import { discardCommitted, isTerminal, type Previews, withOutput } from './conversation.mjs'
import { Activity, Context, Conversation, LiveState, SettingsPanel, Wake } from './Panels'
import { errorMessage, humanize, Icon, Mark } from './ui'

const pages = [
  ['Overview', 'overview'],
  ['Activity', 'activity'],
  ['Context', 'context'],
  ['Conversation', 'conversation'],
  ['Settings', 'settings'],
] as const
type Page = typeof pages[number][0]

const controls = [
  ['start', 'Start', 'play'],
  ['stop', 'Stop', 'stop'],
  ['restart', 'Restart', 'restart'],
] as const

function modelLabel(name: string) {
  return name === 'FakeSingleMind' ? 'Fake' : name
}

export function App() {
  const hub = window.hub
  const [page, setPage] = useState<Page>('Overview')
  const [status, setStatus] = useState<ProcessStatus | null>(null)
  const [settings, setSettings] = useState<Settings | null>(null)
  const [inspection, setInspection] = useState<Inspection | null>(null)
  const [previews, setPreviews] = useState<Previews>({})
  const [action, setAction] = useState<Control | null>(null)
  const [controlError, setControlError] = useState('')
  const [settingsError, setSettingsError] = useState('')
  const [inspectError, setInspectError] = useState('')
  const [chatDraft, setChatDraft] = useState('')
  const [chatError, setChatError] = useState('')
  const [sendingChat, setSendingChat] = useState(false)
  const statusRef = useRef<ProcessStatus | null>(null)
  const workRef = useRef<{ session: number, queued: boolean } | null>(null)

  const refresh = useCallback(async () => {
    const current = statusRef.current
    if (!hub || current?.state !== 'running') return
    if (workRef.current?.session === current.session) {
      workRef.current.queued = true
      return
    }

    const work = { session: current.session, queued: false }
    const stillCurrent = () => workRef.current === work && statusRef.current?.state === 'running'
    workRef.current = work
    try {
      do {
        work.queued = false
        try {
          const result = await hub.inspect()
          if (!stillCurrent()) return
          setInspection(result)
          setPreviews(previous => discardCommitted(previous, result.dialogue))
          setInspectError('')
        } catch (error) {
          if (!stillCurrent()) return
          setInspectError(`Could not read runtime activity. ${errorMessage(error)}`)
        }
      } while (work.queued && stillCurrent())
    } finally {
      if (workRef.current === work) workRef.current = null
    }
  }, [hub])

  useEffect(() => {
    if (!hub) return
    let active = true
    let pushedStatus = false

    function updateStatus(next: ProcessStatus) {
      const previous = statusRef.current
      if (previous?.session !== next.session) {
        setInspection(null)
        setInspectError('')
      }
      if (previous?.session !== next.session || next.state !== 'running') {
        workRef.current = null
        setPreviews({})
      }
      if (next.state !== 'running') setInspectError('')
      statusRef.current = next
      setStatus(next)
      if (next.state === 'running') void refresh()
    }

    const offStatus = hub.onStatus(next => {
      pushedStatus = true
      updateStatus(next)
    })
    const offOutput = hub.onOutput((output, session) => {
      if (statusRef.current?.session !== session || statusRef.current.state !== 'running') return
      setPreviews(previous => withOutput(previous, output))
      if (output.kind === 'reply.started' || isTerminal(output)) void refresh()
    })
    void hub.status().then(next => {
      if (active && !pushedStatus) updateStatus(next)
    }).catch(error => {
      if (active && !pushedStatus) setControlError(errorMessage(error))
    })
    void hub.settings().then(value => {
      if (active) setSettings(value)
    }).catch(error => {
      if (active) setSettingsError(errorMessage(error))
    })

    const interval = window.setInterval(() => void refresh(), 1000)
    return () => {
      active = false
      workRef.current = null
      statusRef.current = null
      window.clearInterval(interval)
      offStatus()
      offOutput()
    }
  }, [hub, refresh])

  async function control(nextAction: Control) {
    setAction(nextAction)
    setControlError('')
    try {
      const result = await hub.control(nextAction)
      if (nextAction === 'stop' && result.inspection && result.state === 'stopped' &&
          statusRef.current?.session === result.session && statusRef.current.state === 'stopped') {
        setInspection(result.inspection)
      }
    } catch (error) {
      setControlError(errorMessage(error))
    } finally {
      setAction(null)
    }
  }

  async function sendChat() {
    const text = chatDraft.trim()
    if (!text || sendingChat || statusRef.current?.state !== 'running') return false
    setSendingChat(true)
    setChatError('')
    try {
      await hub.sendChat(text)
      setChatDraft('')
      void refresh()
      return true
    } catch (error) {
      setChatError(errorMessage(error))
      return false
    } finally {
      setSendingChat(false)
    }
  }

  const running = status?.state === 'running'
  const transition = status?.state === 'starting' || status?.state === 'stopping'
  const snapshot = inspection?.snapshot ?? null
  const model = running ? snapshot?.model : null
  const dialogue = inspection?.dialogue ?? []
  const shownPreviews = discardCommitted(previews, dialogue)
  const statusText = !hub ? 'Disconnected' : status ? humanize(status.state) : 'Connecting'
  const selectedModel = settings?.backend === 'luna' ? 'gpt-6-luna · Low'
    : settings?.backend === 'fake' ? 'Fake' : '—'
  const modelText = model ? [modelLabel(model.name), model.reasoning && humanize(model.reasoning)].filter(Boolean).join(' · ')
    : running ? '—' : selectedModel
  const processError = controlError || (status?.error && errorMessage(status.error))
  const overview = page === 'Overview'

  return (
    <>
      <a className="skip-link" href="#main">Skip to content</a>
      <div className="shell">
        <aside className="sidebar">
          <div className="brand">
            <Mark />
            <div><p className="title-2">liac-ai</p><p className="caption-5">VTuber Hub</p></div>
          </div>
          <nav className="navigation" aria-label="Main navigation">
            {pages.map(([name, icon]) => (
              <button key={name} aria-current={page === name ? 'page' : undefined}
                className="nav-button title-4" onClick={() => setPage(name)}>
                <Icon name={icon} />{name}
              </button>
            ))}
          </nav>
        </aside>

        <main id="main" tabIndex={-1} className="main">
          <header className="topbar">
            <h1 className="heading-5">{page}</h1>
            <div className="runtime-meta">
              <span className={`status-chip caption-3 ${status?.state ?? ''}`} role="status">
                <span className="indicator" />{statusText}
              </span>
              <span className="meta-chip caption-4">
                <Icon name="model" /><span className="meta-label">Model</span><span>{modelText}</span>
              </span>
              <span className="meta-chip caption-4">
                <Icon name="bridge" /><span className="meta-label">Bridge</span>
                <span>{model ? humanize(model.bridge) : '—'}</span>
              </span>
            </div>
            <div className="controls" aria-label="Runtime controls" role="group">
              {controls.map(([command, label, icon]) => (
                <button className={`button button-sm ${command === 'start' && !running ? 'primary' : ''}`}
                  disabled={!status || Boolean(action) || transition ||
                    (command === 'start' ? running : !running)}
                  onClick={() => void control(command)} key={command}>
                  <Icon name={icon} />{label}
                </button>
              ))}
            </div>
          </header>
          {!hub && <p className="banner" role="alert">Open VTuber Hub in Electron to connect to the runtime.</p>}
          {processError && <p className="banner" role="alert">{processError}</p>}
          {inspectError && <p className="banner" role="alert">{inspectError}</p>}
          <div className={`workspace ${overview ? 'overview' : `view-${page.toLowerCase()}`}`}>
            {(overview || page === 'Activity') && (
              <Activity key={status?.session} events={inspection?.activity ?? []} running={running} />
            )}
            {(overview || page === 'Context') && (
              <div className="context-column">
                <Wake snapshot={running ? snapshot : null} />
                <LiveState items={running ? snapshot?.live_state ?? [] : []} running={running} setScene={async text => {
                  await hub.setScene(text)
                  void refresh()
                }} />
                <Context snapshot={snapshot} dialogue={dialogue} />
              </div>
            )}
            {(overview || page === 'Conversation') && (
              <Conversation dialogue={dialogue} previews={shownPreviews} running={running}
                draft={chatDraft} setDraft={setChatDraft} sending={sendingChat} error={chatError} sendChat={sendChat} />
            )}
            {page === 'Settings' && (settings
              ? <SettingsPanel settings={settings} transition={transition} running={running} saveSettings={async draft => {
                  const saved = await hub.saveSettings(draft)
                  setSettings(saved)
                  return saved
                }} />
              : <p className={settingsError ? 'banner' : 'empty'} role={settingsError ? 'alert' : 'status'}>
                  {settingsError || (hub ? 'Loading settings…' : 'Settings are unavailable without Electron.')}
                </p>)}
          </div>
        </main>
      </div>
    </>
  )
}
