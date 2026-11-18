import assert from 'node:assert/strict'
import test from 'node:test'
import { discardCommitted, groupDialogue, previewText, withOutput } from './conversation.mts'

test('provisional speech is assembled once in delta order and replaced by a committed reply', () => {
  const output = (kind, delta_index = 0, text = '') => ({ kind, turn_id: 'turn-1', delta_index, text })
  let previews = withOutput({}, output('reply.started'))
  previews = withOutput(previews, output('reply.delta', 2, ' world'))
  previews = withOutput(previews, output('reply.delta', 1, 'Hello'))
  previews = withOutput(previews, output('reply.delta', 2, 'duplicate'))
  assert.equal(previewText(previews['turn-1']), 'Hello world')

  previews = withOutput(previews, output('reply.completed', 0, 'Hello world!'))
  assert.equal(previews['turn-1'].closed, true)
  assert.equal(withOutput(previews, output('reply.delta', 3, '!')), previews)
  assert.deepEqual(discardCommitted(previews, [{ kind: 'user.message.completed', turn_id: 'turn-1' }]), previews)
  for (const kind of ['completed', 'cancelled', 'failed']) {
    assert.deepEqual(discardCommitted(previews, [{ kind: `character.reply.${kind}`, turn_id: 'turn-1' }]), {})
  }
})

test('a superseded turn keeps its cancellation next to its own user message', () => {
  const item = (sequence, kind, turn_id) => ({ sequence, kind, event_id: `event-${sequence}`, turn_id })
  const orphan = item(1, 'character.reply.completed', 'older')
  const userA = item(2, 'user.message.completed', 'A')
  const userB = item(3, 'user.message.completed', 'B')
  const cancelledA = item(4, 'character.reply.cancelled', 'A')
  const completedB = item(5, 'character.reply.completed', 'B')

  assert.deepEqual(groupDialogue([orphan, userA, userB, cancelledA, completedB], {}).map(group => group.events),
    [[orphan], [userA, cancelledA], [userB, completedB]])

  const previews = withOutput({}, { kind: 'reply.delta', turn_id: 'B', delta_index: 1, text: 'Hello' })
  const groups = groupDialogue([userA, userB, cancelledA], previews)
  assert.equal(groups[0].preview, undefined)
  assert.equal(previewText(groups[1].preview), 'Hello')
})
