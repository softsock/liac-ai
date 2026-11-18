import type { ReactNode } from 'react'

const paths = {
  overview: 'M3 10.5 12 3l9 7.5V21h-6v-7H9v7H3z',
  activity: 'M2 12h5l3-7 4 14 3-7h5',
  context: 'M12 6v15M3 4h4a5 5 0 0 1 5 5 5 5 0 0 1 5-5h4v14h-4a5 5 0 0 0-5 3 5 5 0 0 0-5-3H3z',
  conversation: 'M20 12a8 8 0 0 1-8 8 9 9 0 0 1-3.7-.8L4 20.4l1.2-4.3A8 8 0 1 1 20 12ZM8 12h.1m3.9 0h.1m3.9 0h.1',
  settings: 'm9 3-.7 2.3L6 6l-2.3-.7L2 8l1.7 1.7v4.6L2 16l1.7 2.7L6 18l2.3.7L9 21h6l.7-2.3 2.3-.7 2.3.7L22 16l-1.7-1.7V9.7L22 8l-1.7-2.7L18 6l-2.3-.7L15 3z M15 12a3 3 0 1 1-6 0 3 3 0 1 1 6 0Z',
  wake: 'm13 2-9 12h7l-1 8 10-12h-7z',
  scene: 'M3 3h18v18H3zM3 17l6-6 4 4 2-2 6 6M15 8h.01',
  play: 'M8 5v14l11-7z',
  stop: 'M6 6h12v12H6z',
  restart: 'M3 5v5h5M3.8 9.2a8 8 0 1 1 .8 7.1',
  send: 'M3 3l18 9-18 9 4-9zm4 9h14',
  chevron: 'm9 5 7 7-7 7',
  model: 'M8 3h8m-4 0v4m-9 4h3m12 0h3M5 7h14v12H5zm4 5h.01m5.99 0h.01M9 16h6',
  bridge: 'M2 12h4m12 0h4m-16-4h4v8H6zm8 0h4v8h-4z',
} as const

export type IconName = keyof typeof paths

export function Icon({ name }: { name: IconName }) {
  return (
    <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={paths[name]} />
    </svg>
  )
}

export function Mark() {
  return <span className="mark" aria-hidden="true" />
}

export function Panel({ title, icon, aside, children, className = '' }: {
  title: string
  icon: IconName
  aside?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={`panel ${className}`} aria-label={title}>
      <header className="panel-header">
        <h2><Icon name={icon} />{title}</h2>
        {aside}
      </header>
      {children}
    </section>
  )
}

const time = new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' })

export function formatTime(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : time.format(date)
}

export function humanize(value: string) {
  const words = value.replaceAll('_', ' ')
  return words.charAt(0).toUpperCase() + words.slice(1)
}

const errors: Record<string, string> = {
  backend_exited: 'Python exited unexpectedly. Check Settings and start the runtime again.',
  backend_not_running: 'Start the runtime to continue.',
  bridge_not_found: 'The Luna bridge script could not be found.',
  bun_not_found: 'Bun could not be found. Check the executable in Settings.',
  frame_too_large: 'The request exceeds the transport limit. Try shorter text.',
  invalid_backend_frame: 'Python sent an invalid response. Restart the runtime.',
  invalid_settings: 'Enter valid paths or executable names in Settings.',
  invalid_text: 'Enter some text to continue.',
  oauth_unavailable: 'Luna could not access its local OAuth session.',
  operation_failed: 'The runtime could not complete this request.',
  provider_error: 'The Luna provider returned an error.',
  python_start_failed: 'Python could not start. Check the executable in Settings.',
  request_timeout: 'The runtime did not respond in time.',
  settings_write_failed: 'The settings file could not be saved.',
  startup_failed: 'The runtime could not start. Check the selected backend and paths in Settings.',
  startup_timeout: 'Python did not become ready in time. Check the executable in Settings.',
  text_too_large: 'The text exceeds the runtime limit. Try a shorter message.',
  transport_failed: 'The connection to Python was interrupted.',
}

export function errorMessage(error: unknown) {
  const value = error instanceof Error ? error.message : String(error)
  const code = value.trim().split(/\s/).at(-1) ?? ''
  return errors[code] ?? (code === value && /^[A-Za-z_]+$/.test(code)
    ? humanize(code)
    : 'The operation failed.')
}
