import { useLayoutEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import type { HubEvent, RuntimeSnapshot, Settings } from '../contract'
import { groupDialogue, previewText, type Previews } from './conversation.mjs'
import { errorMessage, formatTime, humanize, Icon, Mark, Panel } from './ui'

const filters = ['All', 'Chat', 'Perception', 'Generation'] as const
type Category = Exclude<typeof filters[number], 'All'>

function describeEvent(event: HubEvent): { label: string, category: Category, summary: string } {
  if (event.kind === 'user.message.completed') {
    return { label: 'User message', category: 'Chat', summary: event.text }
  }
  if (event.kind === 'perception.received') {
    return { label: 'Perception received', category: 'Perception', summary: event.text }
  }

  const kind = event.kind.replace('character.reply.', '')
  const label = kind === 'completed' && event.action === 'stay_silent'
    ? 'Stayed silent' : `Reply ${kind}`
  return { label, category: 'Generation', summary: event.text }
}

export function Activity({ events, running }: { events: HubEvent[], running: boolean }) {
  const [filter, setFilter] = useState<typeof filters[number]>('All')
  const [expanded, setExpanded] = useState<string | null>(null)
  const rows = events.map(event => ({ event, ...describeEvent(event) }))
    .filter(row => filter === 'All' || row.category === filter)

  return (
    <Panel title="Activity" icon="activity" className="activity-panel"
      aside={<span className="caption-5">Latest 100 events</span>}>
      <div className="filters" role="group" aria-label="Filter activity">
        {filters.map(name => (
          <button className="filter button-xsm" aria-pressed={filter === name} key={name}
            onClick={() => setFilter(name)}>{name}</button>
        ))}
      </div>
      <div className="activity-scroll">
        {rows.length === 0 && (
          <p className="empty">{events.length ? 'No events match this filter.'
            : running ? 'Messages, scene updates, and replies will appear here.'
              : 'Start the runtime to view its journal.'}</p>
        )}
        <ul className="events">
          {rows.map(({ event, label, category, summary }) => {
            const isExpanded = expanded === event.event_id
            return (
              <li className={isExpanded ? 'expanded' : ''} key={event.event_id}>
                <button className="event-row" aria-expanded={isExpanded}
                  aria-controls={`event-${event.sequence}`}
                  onClick={() => setExpanded(isExpanded ? null : event.event_id)}>
                  <time className="caption-5 mono" dateTime={event.occurred_at}>{formatTime(event.occurred_at)}</time>
                  <span className={`event-category caption-3 ${category.toLowerCase()}`}>{category}</span>
                  <span className="event-copy">
                    <span className="title-4">{label}</span>
                    {summary && <span className="caption-5 event-summary">{summary}</span>}
                  </span>
                  <Icon name="chevron" />
                </button>
                <div id={`event-${event.sequence}`} className="event-detail" hidden={!isExpanded}>
                  <p className="mono caption-4">{event.kind}</p>
                  <dl className="detail-grid caption-5">
                    <dt>Sequence</dt><dd>{event.sequence}</dd>
                    {event.source && <><dt>Source</dt><dd>{event.source}</dd></>}
                    {event.turn_id && <><dt>Turn</dt><dd className="mono">{event.turn_id}</dd></>}
                    {event.action && <><dt>Action</dt><dd>{humanize(event.action)}</dd></>}
                  </dl>
                  {summary && <p className="event-full body-6">{summary}</p>}
                </div>
              </li>
            )
          })}
        </ul>
      </div>
    </Panel>
  )
}

const wakeReasons: Record<string, string> = {
  new_direct: 'A new direct message triggered a turn.',
  ambient_only: 'An ambient update changed Live State.',
  duplicate: 'The perception was already received.',
  noise_only: 'The runtime ignored noise.',
}

export function Wake({ snapshot }: { snapshot: RuntimeSnapshot | null }) {
  const wake = snapshot?.wake
  const perception = snapshot?.perception

  return (
    <Panel title="Wake" icon="wake" aside={snapshot && (
      <span className={`wake-state caption-4 ${snapshot.runtime.state}`}>
        {humanize(snapshot.runtime.state)}
      </span>
    )}>
      <div className="panel-body wake-body">
        {wake?.decision == null
          ? <p className="empty">No wake decision yet.</p>
          : <div className="wake-decision">
              <span className={`indicator ${wake.decision ? 'violet' : ''}`} />
              <div>
                <p className="title-4">{wake.decision ? 'Started a turn' : 'No turn started'}</p>
                {wake.reason && <p className="caption-5">{wakeReasons[wake.reason] ?? humanize(wake.reason)}</p>}
              </div>
            </div>}
        {perception && (
          <p className="latest-perception caption-5">
            <span>{humanize(perception.kind)} · {perception.source}</span>
            <time className="mono" dateTime={perception.occurred_at}>{formatTime(perception.occurred_at)}</time>
          </p>
        )}
      </div>
    </Panel>
  )
}

export function LiveState({ items, running, setScene }: {
  items: RuntimeSnapshot['live_state']
  running: boolean
  setScene: (text: string) => Promise<void>
}) {
  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const [confirmation, setConfirmation] = useState('')

  async function submit(event: FormEvent) {
    event.preventDefault()
    const value = draft.trim()
    if (!running || sending || !value) return
    setSending(true)
    setError('')
    setConfirmation('')
    try {
      await setScene(value)
      setDraft('')
      setConfirmation('Scene updated.')
    } catch (failure) {
      setError(errorMessage(failure))
    } finally {
      setSending(false)
    }
  }

  return (
    <Panel title="Live State" icon="scene">
      <div className="panel-body live-state-body">
        <p className="caption-4 section-label">Current ambient state</p>
        {items.length === 0 ? <p className="empty">No active observations.</p> : (
          <ul className="observations">
            {items.map(item => (
              <li key={`${item.source}:${item.kind}`}>
                <div className="observation-meta caption-5">
                  <span>{humanize(item.kind)} · {item.source}</span>
                  <span className="ttl mono" title="Expires in">{Math.ceil(item.expires_in_seconds)} s left</span>
                </div>
                <p className="body-6">{item.text}</p>
              </li>
            ))}
          </ul>
        )}
        <form className="scene-form" onSubmit={submit}>
          <label className="visually-hidden" htmlFor="scene-description">Scene description</label>
          <input id="scene-description" value={draft} onChange={event => setDraft(event.target.value)}
            placeholder="Describe the scene" disabled={!running || sending} required />
          <button className="button button-sm" type="submit" disabled={!running || sending || !draft.trim()}>
            {sending ? 'Setting…' : 'Set scene'}
          </button>
        </form>
        {error && <p className="inline-error caption-5" role="alert">{error}</p>}
        <p className="caption-5" role="status">{running ? confirmation : 'Start the runtime to set a scene.'}</p>
      </div>
    </Panel>
  )
}

const number = new Intl.NumberFormat('en-US')
const frameLimit = 63 * 1024
const metrics = [
  ['first_tool_delta_ms', 'First tool delta'],
  ['bridge_duration_ms', 'Bridge duration'],
  ['duration_ms', 'Runtime duration'],
] as const
const usageMetrics = [
  ['input', 'Input tokens'],
  ['output', 'Output tokens'],
  ['cacheRead', 'Cache read tokens'],
  ['cacheWrite', 'Cache write tokens'],
  ['totalTokens', 'Total tokens'],
] as const

function flag(value: boolean | null) {
  return value === null ? '—' : value ? 'Yes' : 'No'
}

export function Context({ snapshot, dialogue }: { snapshot: RuntimeSnapshot | null, dialogue: HubEvent[] }) {
  const context = snapshot?.context
  const bytes = context?.frame_bytes
  const generation = snapshot?.generation
  const recent = dialogue.filter(event =>
    event.kind === 'user.message.completed' || event.kind === 'character.reply.completed').slice(-3)

  return (
    <Panel title="Context" icon="context">
      <div className="panel-body context-body">
        <div className="frame-heading">
          <span className="caption-4">Last assembled frame</span>
          <span className="mono caption-4">{bytes == null ? '—' : `${number.format(bytes)} B`} / 63 KiB</span>
        </div>
        {bytes == null
          ? <div className="frame-meter" aria-hidden="true" />
          : <progress className="frame-meter" aria-label="Frame bytes" max={frameLimit} value={bytes} />}
        {bytes == null && <p className="empty">Send a message to compile a context frame.</p>}
        {context && bytes != null && (
          <dl className="context-stats caption-5">
            <div><dt>History turns</dt><dd className="mono">{context.history_turns ?? '—'}</dd></div>
            <div><dt>Sensor block included</dt><dd>{flag(context.sensor_included)}</dd></div>
            <div><dt>Older history omitted</dt><dd>{flag(context.older_history_omitted)}</dd></div>
          </dl>
        )}
        {generation && (metrics.some(([key]) => generation[key] != null) || generation.usage) && (
          <div className="context-subsection">
            <h3 className="caption-4 section-label">Generation measurements</h3>
            <dl className="context-stats caption-5">
              {metrics.map(([key, label]) => {
                const value = generation[key]
                return value == null ? null : <div key={key}><dt>{label}</dt><dd className="mono">{number.format(value)} ms</dd></div>
              })}
              {usageMetrics.map(([key, label]) => {
                const value = generation.usage?.[key]
                return value == null ? null : <div key={key}><dt>{label}</dt><dd className="mono">{number.format(value)}</dd></div>
              })}
            </dl>
          </div>
        )}
        <div className="context-subsection">
          <h3 className="caption-4 section-label">Recent dialogue</h3>
          {recent.length === 0 ? <p className="empty">No messages yet.</p> : (
            <ul className="recent-dialogue caption-5">
              {recent.map(event => (
                <li key={event.event_id}>
                  <strong>{event.kind === 'user.message.completed' ? 'You' : 'VTuber'}</strong>
                  <span>{event.action === 'stay_silent' ? 'Stayed silent' : event.text}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </Panel>
  )
}

function DialogueEntry({ event }: { event: HubEvent }) {
  if (event.kind !== 'user.message.completed' && event.kind !== 'character.reply.completed') {
    const failed = event.kind === 'character.reply.failed'
    const reason = event.text && (failed ? errorMessage(event.text) : humanize(event.text))
    return <p className={`conversation-note caption-5 ${failed ? 'failure' : 'cancelled'}`}>
      {failed ? 'Reply failed' : 'Reply cancelled'}{reason && ` · ${reason}`}
    </p>
  }
  if (event.action === 'stay_silent') {
    return <p className="conversation-note caption-5">The VTuber stayed silent.</p>
  }
  const outgoing = event.kind === 'user.message.completed'
  return (
    <div className={`message ${outgoing ? 'outgoing' : 'incoming'}`}>
      {!outgoing && <Mark />}
      <div className="message-content">
        <div className="message-meta caption-5">
          <strong>{outgoing ? 'You' : 'VTuber'}</strong>
          <time className="mono" dateTime={event.occurred_at}>{formatTime(event.occurred_at)}</time>
        </div>
        <p className="body-6">{event.text}</p>
      </div>
    </div>
  )
}

export function Conversation({ dialogue, previews, running, draft, setDraft, sending, error, sendChat }: {
  dialogue: HubEvent[]
  previews: Previews
  running: boolean
  draft: string
  setDraft: (text: string) => void
  sending: boolean
  error: string
  sendChat: () => Promise<boolean>
}) {
  const transcript = useRef<HTMLDivElement>(null)
  const follow = useRef(true)
  const turns = groupDialogue(dialogue, previews)

  useLayoutEffect(() => {
    const node = transcript.current
    if (follow.current && node) node.scrollTop = node.scrollHeight
  }, [dialogue, previews])

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (await sendChat()) {
      follow.current = true
      if (transcript.current) transcript.current.scrollTop = transcript.current.scrollHeight
    }
  }

  return (
    <Panel title="Conversation" icon="conversation" className="conversation-panel">
      <div className="transcript" role="region" aria-label="Conversation transcript" tabIndex={0}
        ref={transcript} onScroll={event => {
        const node = event.currentTarget
        follow.current = node.scrollHeight - node.clientHeight - node.scrollTop < 48
      }}>
        {turns.length === 0 && (
          <div className="chat-empty">
            <div className="empty-icon"><Icon name="conversation" /></div>
            <p className="title-3">No messages yet</p>
            <p className="caption-2">{running ? 'Send a message to the VTuber.' : 'Start the runtime to open the conversation.'}</p>
          </div>
        )}
        <div className="messages" role="log" aria-label="Conversation journal" aria-live="polite">
          {turns.map(({ key, events, preview }) => (
            <div className="messages" key={key}>
              {events.map(event => <DialogueEntry key={event.event_id} event={event} />)}
              {preview && (
                <div className="message incoming provisional" aria-live="off">
                  <Mark />
                  <div className="message-content">
                    <div className="message-meta caption-5"><strong>VTuber</strong><span>Provisional</span></div>
                    <p className="body-6">{previewText(preview) || (preview.closed ? 'Saving reply…' : 'Thinking…')}</p>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
      <form className="composer" onSubmit={submit}>
        <div className="composer-row">
          <label className="visually-hidden" htmlFor="chat-text">Message the VTuber</label>
          <textarea id="chat-text" rows={2} required value={draft}
            placeholder={running ? 'Message the VTuber…' : 'Runtime is offline'}
            onChange={event => setDraft(event.target.value)} readOnly={!running || sending}
            onKeyDown={event => {
              if (!running || sending || event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing) return
              event.preventDefault()
              event.currentTarget.form?.requestSubmit()
            }} />
          <button className="button primary send-button" type="submit" disabled={!running || sending || !draft.trim()}
            aria-label="Send message"><Icon name="send" /></button>
        </div>
        {error && <p className="inline-error caption-5" role="alert">{error}</p>}
        {running && <p className="composer-help caption-5">Enter to send · Shift + Enter for a new line</p>}
      </form>
    </Panel>
  )
}

export function SettingsPanel({ settings, transition, running, saveSettings }: {
  settings: Settings
  transition: boolean
  running: boolean
  saveSettings: (value: Settings) => Promise<Settings>
}) {
  const [draft, setDraft] = useState(settings)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  async function submit(event: FormEvent) {
    event.preventDefault()
    setSaving(true)
    setError('')
    setNotice('')
    try {
      setDraft(await saveSettings(draft))
      setNotice(running ? 'Settings saved. Restart the runtime to apply them.' : 'Settings saved.')
    } catch (failure) {
      setError(errorMessage(failure))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Panel title="Runtime settings" icon="settings" className="settings-panel">
      <form className="settings-form" onSubmit={submit}>
        <fieldset disabled={saving || transition}>
          <div className="setting-field">
            <label className="title-4" htmlFor="backend">Backend</label>
            <select id="backend" value={draft.backend} onChange={event =>
              setDraft({ ...draft, backend: event.target.value as Settings['backend'] })}>
              <option value="fake">Fake</option>
              <option value="luna">Luna</option>
            </select>
            <p className="caption-5">Luna uses the fixed model <span className="mono">gpt-6-luna</span> with low reasoning.</p>
          </div>
          <div className="setting-field">
            <label className="title-4" htmlFor="python">Python executable</label>
            <input id="python" value={draft.python} placeholder="Use default Python" onChange={event =>
              setDraft({ ...draft, python: event.target.value })} />
            <p className="caption-5">An executable name on PATH or the path to Python 3.12 or newer.</p>
          </div>
          <div className="setting-field">
            <label className="title-4" htmlFor="bun">Bun executable</label>
            <input id="bun" value={draft.bun} placeholder="Use default Bun" onChange={event =>
              setDraft({ ...draft, bun: event.target.value })} />
            <p className="caption-5">Used by the Luna bridge. Fake mode runs without Bun.</p>
          </div>
          <div className="setting-field">
            <label className="title-4" htmlFor="db">SQLite path</label>
            <input id="db" value={draft.db} placeholder="Use backend default" onChange={event =>
              setDraft({ ...draft, db: event.target.value })} />
            <p className="caption-5">Leave this empty to use the selected backend's default journal.</p>
          </div>
          <p className="caption-5">Saved locally. Changes apply when the runtime next starts.</p>
          <button className="button primary button-sm" type="submit">{saving ? 'Saving…' : 'Save settings'}</button>
        </fieldset>
        {error && <p className="inline-error caption-5" role="alert">{error}</p>}
        {notice && <p className="caption-5" role="status">{notice}</p>}
      </form>
    </Panel>
  )
}
