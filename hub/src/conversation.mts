import type { HubEvent, RuntimeOutput } from '../contract'

interface Preview {
  chunks: Record<number, string>
  closed: boolean
}

export type Previews = Record<string, Preview>

const terminalKinds = new Set(['reply.completed', 'reply.cancelled', 'reply.failed'])

export function isTerminal(output: RuntimeOutput): boolean {
  return terminalKinds.has(output.kind)
}

export function withOutput(previews: Previews, output: RuntimeOutput): Previews {
  const turn = output.turn_id
  if (!turn) return previews
  const previous = previews[turn] ?? { chunks: {}, closed: false }
  if (previous.closed) return previews

  if (isTerminal(output)) return { ...previews, [turn]: { ...previous, closed: true } }
  if (output.kind === 'reply.started') return turn in previews ? previews : { ...previews, [turn]: previous }
  if (output.kind !== 'reply.delta' || output.delta_index in previous.chunks) return previews
  return { ...previews, [turn]: { ...previous, chunks: { ...previous.chunks, [output.delta_index]: output.text } } }
}

export function discardCommitted(previews: Previews, dialogue: HubEvent[]): Previews {
  const remaining = { ...previews }
  for (const event of dialogue) {
    if (event.turn_id && terminalKinds.has(event.kind.replace(/^character\./, ''))) {
      delete remaining[event.turn_id]
    }
  }
  return remaining
}

export function previewText(preview: Preview): string {
  return Object.values(preview.chunks).join('')
}

export function groupDialogue(dialogue: HubEvent[], previews: Previews) {
  const groups = new Map<string, { key: string, events: HubEvent[], preview?: Preview }>()
  for (const event of dialogue) {
    const key = event.turn_id ?? event.event_id
    const group = groups.get(key) ?? { key, events: [] }
    group.events.push(event)
    groups.set(key, group)
  }
  for (const [key, preview] of Object.entries(previews)) {
    const group = groups.get(key) ?? { key, events: [] }
    groups.set(key, { ...group, preview })
  }
  return [...groups.values()]
}
