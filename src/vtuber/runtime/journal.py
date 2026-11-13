"""SQLite transactions own event ordering, state, proposal decisions and Deep ack."""

import json
import sqlite3
from hashlib import sha256
from contextlib import contextmanager
from dataclasses import asdict, replace
from pathlib import Path
from typing import Iterator
from datetime import datetime, timezone
from typing import Callable
from time import monotonic as monotonic_time

from vtuber.contracts.events import CharacterId, Event, canonical_json, utc_now
from vtuber.contracts.context import CompactionProposal, CompactionResult, ContextEpoch, ContextItem
from vtuber.contracts.state import CharacterState, FastSnapshot, NoteProposal, UpdateResult
from vtuber.runtime.state import RevisionConflict, reduce_note
from vtuber.contracts.deep import CompactionInput, DeepRequest, DeepResult, DeepDecision, evidence_ids
from vtuber.contracts.attention import AttentionSignal, AttentionView, STATUSES
from vtuber.runtime.attention import attention_key, decode_signal, prepare_attention, rank_signal


class EventConflict(ValueError):
    """An idempotency identifier was reused with different content."""


class Journal:
    def __init__(self, path: str | Path, *, clock: Callable[[], datetime] | None = None,
                 monotonic: Callable[[], float] = monotonic_time) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._monotonic = monotonic
        self._attention_deadlines: dict[str, tuple[int, float, str]] = {}
        self._deadline_rollback = None
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        try:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=FULL")
            version = self._db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2, 3):
                raise ValueError(f"Unsupported database version: {version}")
            with self._transaction():
                self._db.execute("""CREATE TABLE IF NOT EXISTS events (
                    character_id TEXT NOT NULL, sequence INTEGER NOT NULL,
                    event_id TEXT NOT NULL UNIQUE, content TEXT NOT NULL,
                    recorded_at TEXT NOT NULL, PRIMARY KEY(character_id, sequence))""")
                self._db.execute("""CREATE TABLE IF NOT EXISTS character_state (
                    character_id TEXT PRIMARY KEY, revision INTEGER NOT NULL DEFAULT 0,
                    context_note TEXT NOT NULL DEFAULT '', deep_cursor INTEGER NOT NULL DEFAULT 0)""")
                self._db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS user_turn ON events
                    (character_id, json_extract(content, '$.turn_id'))
                    WHERE json_extract(content, '$.kind') = 'user.message.completed'""")
                self._db.execute("""CREATE TABLE IF NOT EXISTS context_epochs (
                    character_id TEXT NOT NULL, version INTEGER NOT NULL, content TEXT NOT NULL,
                    PRIMARY KEY(character_id, version))""")
                self._db.execute("""CREATE TABLE IF NOT EXISTS attention_signals (
                    character_id TEXT NOT NULL, signal_id TEXT PRIMARY KEY, provenance_key TEXT NOT NULL,
                    creation_sequence INTEGER NOT NULL, content TEXT NOT NULL,
                    UNIQUE(character_id, provenance_key))""")
                needs_aliases = version == 3 and self._db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='attention_provenance'").fetchone() is None
                self._db.execute("""CREATE TABLE IF NOT EXISTS attention_provenance (
                    character_id TEXT NOT NULL, provenance_key TEXT NOT NULL, signal_id TEXT NOT NULL,
                    PRIMARY KEY(character_id, provenance_key))""")
                if needs_aliases:
                    # Recover aliases when opening a development v3 database made before this index.
                    for row in self._db.execute("""SELECT content FROM events WHERE
                        json_extract(content, '$.kind') LIKE 'attention.signal.%' ORDER BY sequence"""):
                        signal = json.loads(row[0])['payload_json']
                        signal = json.loads(signal)['signal']
                        self._db.execute('INSERT OR IGNORE INTO attention_provenance VALUES (?, ?, ?)',
                            (signal['character_id'], attention_key(signal['character_id'], signal['kind'],
                             tuple(signal['source_event_ids'])), signal['signal_id']))
                self._db.execute("PRAGMA user_version=3")
        except BaseException:
            self._db.close()
            raise

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        self._db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self._db.execute("COMMIT")
        except BaseException:
            self._db.execute("ROLLBACK")
            if self._deadline_rollback is not None:
                self._attention_deadlines = self._deadline_rollback
            raise
        finally:
            self._deadline_rollback = None

    def close(self) -> None:
        self._db.close()

    @staticmethod
    def _decode(row: sqlite3.Row) -> Event:
        return Event(**json.loads(row["content"]), sequence=row["sequence"],
                     recorded_at=row["recorded_at"])

    def get(self, event_id: str) -> Event | None:
        row = self._db.execute("SELECT * FROM events WHERE event_id=?", (event_id,)).fetchone()
        return self._decode(row) if row else None

    def high_watermark(self, character_id: CharacterId) -> int:
        return self._db.execute("SELECT COALESCE(MAX(sequence), 0) FROM events WHERE character_id=?",
                                (character_id,)).fetchone()[0]

    def _append(self, event: Event) -> Event:
        content = asdict(event)
        del content["sequence"], content["recorded_at"]
        encoded = canonical_json(content)
        previous = self._db.execute("SELECT * FROM events WHERE event_id=?",
                                    (event.event_id,)).fetchone()
        if previous:
            if previous["content"] != encoded:
                raise EventConflict(f"event_id conflict: {event.event_id}")
            return self._decode(previous)
        self._db.execute("INSERT OR IGNORE INTO character_state(character_id) VALUES (?)",
                         (event.character_id,))
        stored = replace(event, sequence=self.high_watermark(event.character_id) + 1,
                         recorded_at=utc_now())
        self._db.execute("INSERT INTO events VALUES (?, ?, ?, ?, ?)",
                         (stored.character_id, stored.sequence, stored.event_id,
                          encoded, stored.recorded_at))
        return stored

    def append(self, event: Event) -> Event:
        with self._transaction():
            return self._append(event)

    def read(self, character_id: CharacterId, *, after: int = 0,
             limit: int = 100) -> tuple[Event, ...]:
        if after < 0 or limit < 1:
            raise ValueError("after must be nonnegative and limit positive")
        rows = self._db.execute("""SELECT * FROM events WHERE character_id=? AND sequence>?
            ORDER BY sequence LIMIT ?""", (character_id, after, limit)).fetchall()
        return tuple(self._decode(row) for row in rows)

    def recent_dialogue(self, character_id: CharacterId, limit: int = 20) -> tuple[Event, ...]:
        rows = self._db.execute("""SELECT * FROM events WHERE character_id=? AND
            json_extract(content, '$.kind') IN ('user.message.completed', 'character.reply.completed')
            ORDER BY sequence DESC LIMIT ?""", (character_id, limit)).fetchall()
        return tuple(self._decode(row) for row in reversed(rows))

    def snapshot(self, character_id: CharacterId) -> CharacterState:
        row = self._db.execute("SELECT * FROM character_state WHERE character_id=?",
                               (character_id,)).fetchone()
        return CharacterState(character_id, row["revision"], row["context_note"]) if row else CharacterState(character_id)

    def context_epoch(self, character_id: CharacterId) -> ContextEpoch:
        row = self._db.execute("""SELECT content FROM context_epochs WHERE character_id=?
            ORDER BY version DESC LIMIT 1""", (character_id,)).fetchone()
        if row is None:
            return ContextEpoch()
        data = json.loads(row[0])
        items = tuple(ContextItem(**{**item, "source_event_ids": tuple(item["source_event_ids"])})
                      for item in data.pop("items"))
        return ContextEpoch(**data, items=items)

    def fast_snapshot(self, character_id: CharacterId) -> FastSnapshot:
        self._db.execute("BEGIN")
        try:
            state = self.snapshot(character_id)
            epoch = self.context_epoch(character_id)
            high = self.high_watermark(character_id)
            rows = self._db.execute("""SELECT * FROM events WHERE character_id=? AND sequence>?
                AND sequence<=? AND json_extract(content, '$.kind') IN
                ('user.message.completed', 'character.reply.completed') ORDER BY sequence""",
                (character_id, epoch.compacted_through_sequence, high)).fetchall()
            terminals = self._db.execute("""SELECT content, sequence FROM events WHERE character_id=?
                AND sequence>? AND sequence<=? AND json_extract(content, '$.kind') IN
                ('character.reply.completed', 'character.reply.cancelled', 'character.reply.failed')
                ORDER BY sequence""", (character_id, epoch.compacted_through_sequence, high)).fetchall()
            return FastSnapshot(state, high, tuple(self._decode(row) for row in rows), epoch,
                tuple((json.loads(row["content"])["turn_id"], row["sequence"]) for row in terminals))
        finally:
            self._db.execute("COMMIT")

    def apply_compaction(self, proposal: CompactionProposal) -> CompactionResult:
        with self._transaction():
            return self._apply_compaction(proposal)

    def _apply_compaction(self, proposal: CompactionProposal) -> CompactionResult:
        # Reject malformed identities before SQL binding or constructing audit IDs.
        for value in (proposal.proposal_id, proposal.character_id):
            if not isinstance(value, str) or not 1 <= len(value.strip()) <= 200:
                raise ValueError("Invalid compaction identity")
        encoded = canonical_json(asdict(proposal))
        audit_id = f"compaction_{proposal.proposal_id}"
        previous = self.get(audit_id)
        if previous:
            payload = previous.payload
            if payload.get("proposal") != encoded:
                raise EventConflict(f"compaction proposal_id conflict: {proposal.proposal_id}")
            return CompactionResult(payload["accepted"], payload["epoch_version"], payload["reason"])
        epoch = self.context_epoch(proposal.character_id)
        reason = self._validate_compaction(proposal, epoch)
        if not reason:
            epoch = ContextEpoch(epoch.version + 1, proposal.compacted_through_sequence, proposal.items)
            self._db.execute("INSERT INTO context_epochs VALUES (?, ?, ?)",
                (proposal.character_id, epoch.version, canonical_json(asdict(epoch))))
        result = CompactionResult(not reason, epoch.version, reason or "applied")
        self._append(Event.create(proposal.character_id,
            "context.epoch.rejected" if reason else "context.epoch.applied",
            {"proposal": encoded, **asdict(result)}, event_id=audit_id))
        return result

    def _validate_compaction(self, proposal: CompactionProposal, epoch: ContextEpoch) -> str:
        for value in (proposal.based_on_epoch, proposal.based_on_revision,
                      proposal.observed_through_sequence, proposal.compacted_through_sequence):
            if type(value) is not int or not 0 <= value <= 2**63 - 1:
                return "invalid_watermark"
        if proposal.based_on_epoch != epoch.version:
            return "epoch_conflict"
        if proposal.based_on_revision != self.snapshot(proposal.character_id).revision:
            return "revision_conflict"
        cutoff = proposal.compacted_through_sequence
        if not epoch.compacted_through_sequence <= cutoff <= proposal.observed_through_sequence <= self.high_watermark(proposal.character_id):
            return "invalid_watermark"
        if not isinstance(proposal.items, tuple) or len(proposal.items) > 32:
            return "invalid_items"
        for item in proposal.items:
            if (not isinstance(item, ContextItem) or item.kind not in ("extract", "summary")
                    or type(item.truncated) is not bool or not isinstance(item.text, str)
                    or not item.text.strip() or len(item.text) > 8000
                    or not isinstance(item.source_event_ids, tuple) or not 1 <= len(item.source_event_ids) <= 32):
                return "invalid_item"
            sources = []
            for event_id in item.source_event_ids:
                if not isinstance(event_id, str) or not event_id.strip():
                    return "invalid_source"
                source = self.get(event_id)
                if (source is None or source.character_id != proposal.character_id or source.sequence > cutoff
                        or source.kind not in ("user.message.completed", "character.reply.completed")):
                    return "invalid_source"
                sources.append(source)
            if item.kind == "extract":
                if len(sources) != 1:
                    return "invalid_extract"
                text = sources[0].payload.get("text")
                if not isinstance(text, str) or not (item.text == text or
                        (item.truncated and text.startswith(item.text))):
                    return "invalid_extract"
        if cutoff == epoch.compacted_through_sequence:
            return "" if proposal.items != epoch.items else "no_change"
        # Every user turn covered by the cutoff must have ended before it.
        rows = self._db.execute("""SELECT content FROM events WHERE character_id=? AND sequence>? AND sequence<=?
            ORDER BY sequence""", (proposal.character_id, epoch.compacted_through_sequence, cutoff)).fetchall()
        users, terminals = set(), set()
        last_kind = ""
        for row in rows:
            data = json.loads(row[0])
            last_kind = data["kind"]
            if last_kind == "user.message.completed":
                if not data["turn_id"]:
                    return "invalid_cutoff"
                users.add(data["turn_id"])
            if last_kind in ("character.reply.completed", "character.reply.cancelled", "character.reply.failed"):
                terminals.add(data["turn_id"])
        if not users <= terminals or last_kind not in (
                "character.reply.completed", "character.reply.cancelled", "character.reply.failed"):
            return "invalid_cutoff"
        return ""

    def cursor(self, character_id: CharacterId) -> int:
        row = self._db.execute("SELECT deep_cursor FROM character_state WHERE character_id=?",
                               (character_id,)).fetchone()
        return row[0] if row else 0

    def _attention_all(self, character_id: str) -> tuple[AttentionSignal, ...]:
        return tuple(decode_signal(json.loads(row[0])) for row in self._db.execute(
            'SELECT content FROM attention_signals WHERE character_id=? ORDER BY creation_sequence DESC',
            (character_id,)))

    def attention_signals(self, character_id: str, *, status: str | None = None,
                          limit: int = 20, before: int | None = None) -> tuple[AttentionSignal, ...]:
        if (type(limit) is not int or not 1 <= limit <= 100 or status is not None and status not in STATUSES
                or before is not None and (type(before) is not int or before < 1)):
            raise ValueError('Invalid attention filter')
        self.expire_attention(character_id)
        rows = self._db.execute("""SELECT content FROM attention_signals WHERE character_id=?
            AND (? IS NULL OR json_extract(content, '$.status')=?)
            AND (? IS NULL OR creation_sequence<?) ORDER BY creation_sequence DESC LIMIT ?""",
            (character_id, status, status, before, before, limit))
        return tuple(decode_signal(json.loads(row[0])) for row in rows)

    def attention_candidates(self, character_id: str) -> AttentionView:
        self.expire_attention(character_id)
        return AttentionView(self.cursor(character_id), tuple(sorted(
            (s for s in self._attention_all(character_id) if s.status == 'noticed'), key=rank_signal)))

    def _store_attention(self, signal: AttentionSignal, *, request_id: str | None = None) -> None:
        old = self._db.execute('SELECT creation_sequence FROM attention_signals WHERE signal_id=?',
                               (signal.signal_id,)).fetchone()
        action = signal.status if signal.status in ('superseded', 'expired') else ('updated' if old else 'created')
        event = self._append(Event.create(signal.character_id, 'attention.signal.' + action,
            {'signal': asdict(signal), 'request_id': request_id},
            event_id=f'attention_{signal.signal_id}_v{signal.version}'))
        self._db.execute("""INSERT INTO attention_signals VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(signal_id) DO UPDATE SET provenance_key=excluded.provenance_key, content=excluded.content""",
            (signal.character_id, signal.signal_id, attention_key(signal.character_id, signal.kind, signal.source_event_ids),
             old[0] if old else event.sequence, canonical_json(asdict(signal))))
        self._db.execute('INSERT OR IGNORE INTO attention_provenance VALUES (?, ?, ?)',
            (signal.character_id, attention_key(signal.character_id, signal.kind, signal.source_event_ids), signal.signal_id))
        self._attention_expired(signal, self._clock())

    def _attention_expired(self, signal: AttentionSignal, now: datetime) -> bool:
        if self._db.in_transaction and self._deadline_rollback is None:
            self._deadline_rollback = self._attention_deadlines.copy()
        if signal.status not in ('noticed', 'deferred') or signal.expires_at is None:
            self._attention_deadlines.pop(signal.signal_id, None)
            return False
        expiry = datetime.fromisoformat(signal.expires_at)
        previous = self._attention_deadlines.get(signal.signal_id)
        if previous is None or previous[0] != signal.version:
            deadline = self._monotonic() + max(0, (expiry - now).total_seconds())
            if previous is not None and expiry <= datetime.fromisoformat(previous[2]):
                deadline = min(deadline, previous[1])
            previous = (signal.version, deadline, signal.expires_at)
            self._attention_deadlines[signal.signal_id] = previous
        return expiry <= now or self._monotonic() >= previous[1]

    def expire_attention(self, character_id: str) -> int:
        now = self._clock()
        with self._transaction():
            expired = [s for s in self._attention_all(character_id) if self._attention_expired(s, now)]
            for signal in expired:
                self._store_attention(replace(signal, version=signal.version + 1, status='expired', updated_at=now.isoformat()))
            return len(expired)

    def deep_request(self, character_id: str, *, request_id: str,
                     max_events: int = 100, compact: bool = False) -> DeepRequest | None:
        if max_events < 1 or not request_id.strip():
            raise ValueError('Invalid Deep request')
        self.expire_attention(character_id)
        with self._transaction():
            cursor = self.cursor(character_id)
            pending, safe, opened = [], 0, set()
            for row in self._db.execute('SELECT * FROM events WHERE character_id=? AND sequence>? ORDER BY sequence',
                                        (character_id, cursor)):
                event = self._decode(row)
                pending.append(event)
                if event.kind == 'user.message.completed':
                    opened.add(event.turn_id)
                elif event.kind in ('character.reply.completed', 'character.reply.cancelled', 'character.reply.failed'):
                    opened.discard(event.turn_id)
                if not opened:
                    safe = len(pending)
                    if safe >= max_events:
                        break
            events = tuple(pending[:safe])
            if not events and not compact:
                return None
            through = events[-1].sequence if events else cursor
            dialogue = any(e.kind == 'user.message.completed' for e in events)
            if events and not dialogue:
                self._acknowledge(character_id, cursor, through)
                cursor = through
                events = ()
            epoch = self.context_epoch(character_id)
            rows = self._db.execute('SELECT * FROM events WHERE character_id=? AND sequence<=? ORDER BY sequence',
                                    (character_id, through)).fetchall()
            canonical = tuple(self._decode(row) for row in rows)
            terminals = tuple(e for e in canonical if e.kind in (
                'character.reply.completed', 'character.reply.cancelled', 'character.reply.failed'))
            cutoff = terminals[-1].sequence if terminals else 0
            eligible = tuple(e for e in canonical if e.kind in ('user.message.completed', 'character.reply.completed'))
            compaction = None
            if compact and cutoff > epoch.compacted_through_sequence:
                previous = {s for item in epoch.items for s in item.source_event_ids}
                evidence = tuple(e for e in eligible if e.sequence <= cutoff
                    and (e.sequence > epoch.compacted_through_sequence or e.event_id in previous))
                compaction = CompactionInput(cutoff, evidence)
            if not dialogue and compaction is None:
                return None
            snapshot = FastSnapshot(self.snapshot(character_id), through,
                tuple(e for e in eligible if e.sequence > epoch.compacted_through_sequence), epoch,
                tuple((e.turn_id, e.sequence) for e in terminals if e.sequence > epoch.compacted_through_sequence))
            # Audit records are decisions, not new observations for the model.
            observed = tuple(e for e in events if not e.kind.startswith(('deep.', 'state.patch.', 'context.epoch.', 'attention.')))
            attention = tuple(sorted((s for s in self._attention_all(character_id)
                                      if s.status in ('noticed', 'deferred')), key=rank_signal))
            source_ids = {s for signal in attention for s in signal.source_event_ids}
            sources = tuple(e for e in canonical if e.event_id in source_ids)
            return DeepRequest(request_id, snapshot, cursor, observed, compaction, attention, sources)

    def apply_deep(self, request: DeepRequest, result: DeepResult, *,
                   compaction_error: str | None = None) -> DeepDecision:
        fingerprint = sha256(canonical_json({'request': asdict(request), 'result': asdict(result),
            'compaction_error': compaction_error}).encode()).hexdigest()
        character = request.snapshot.state.character_id
        audit_id = 'deep_' + request.request_id
        self.expire_attention(character)
        with self._transaction():
            previous = self.get(audit_id)
            if previous:
                payload = previous.payload
                if payload['fingerprint'] != fingerprint:
                    legacy_request, legacy_result = asdict(request), asdict(result)
                    legacy_request.pop('attention_context')
                    legacy_request.pop('attention_sources')
                    legacy_result.pop('attention')
                    legacy = sha256(canonical_json({'request': legacy_request, 'result': legacy_result,
                        'compaction_error': compaction_error}).encode()).hexdigest()
                    if (result.schema_version != 1 or result.attention or request.attention_context
                            or request.attention_sources or payload['fingerprint'] != legacy):
                        raise EventConflict('Deep request ID conflict')
                value = payload['decision']
                return DeepDecision(value['request_id'], UpdateResult(**value['note']) if value['note'] else None,
                    CompactionResult(**value['compaction']) if value['compaction'] else None,
                    value['acknowledged'], value['reason'], tuple(value.get('attention_signal_ids', ())))
            if result.request_id != request.request_id or type(result.schema_version) is not int or result.schema_version != 2:
                raise ValueError('Invalid Deep result envelope')
            if self.cursor(character) != request.cursor_from:
                raise ValueError('Deep cursor conflict')
            reason = ''
            state = self.snapshot(character)
            epoch = self.context_epoch(character)
            if result.note or result.compaction or result.attention:
                if request.snapshot.state.revision != state.revision:
                    reason = 'revision_conflict'
            if (result.note or result.compaction or result.attention) and request.snapshot.epoch.version != epoch.version:
                reason = reason or 'epoch_conflict'
            evidence = evidence_ids(request)
            if result.note:
                p = result.note
                if (p.proposal_id != request.request_id+':note' or p.character_id != character
                        or p.based_on_revision != request.snapshot.state.revision
                        or p.observed_through_sequence != request.snapshot.through_sequence
                        or not set(p.source_event_ids) <= evidence):
                    reason = reason or 'invalid_note_dependencies'
                reason = reason or self._validate_proposal(p)
            if result.compaction:
                p = result.compaction
                if (request.compaction is None or p.proposal_id != request.request_id+':epoch'
                        or p.character_id != character or p.based_on_epoch != request.snapshot.epoch.version
                        or p.based_on_revision != request.snapshot.state.revision
                        or p.observed_through_sequence != request.snapshot.through_sequence
                        or p.compacted_through_sequence != request.compaction.cutoff
                        or any(s not in evidence for i in p.items for s in i.source_event_ids)):
                    reason = reason or 'invalid_compaction_dependencies'
                reason = reason or compaction_error or self._validate_compaction(p, epoch)
            provenance = dict(self._db.execute('SELECT provenance_key, signal_id FROM attention_provenance WHERE character_id=?',
                                               (character,)).fetchall())
            attention_changes = prepare_attention(request, result, self._attention_all(character), self.get, self._clock(), provenance)
            note_result = compaction_result = None
            if reason:
                if result.note:
                    note_result = UpdateResult(False, state.revision, reason)
                    self._append(Event.create(character, 'state.patch.rejected',
                        {'proposal': canonical_json(asdict(result.note)), **asdict(note_result)},
                        event_id='proposal_'+result.note.proposal_id))
                if result.compaction:
                    compaction_result = CompactionResult(False, epoch.version, reason)
                    self._append(Event.create(character, 'context.epoch.rejected',
                        {'proposal': canonical_json(asdict(result.compaction)), **asdict(compaction_result)},
                        event_id='compaction_'+result.compaction.proposal_id))
            else:
                if result.compaction:
                    compaction_result = self._apply_compaction(result.compaction)
                if result.note:
                    note_result = self._apply_note(result.note)
                for signal in attention_changes:
                    self._store_attention(signal, request_id=request.request_id)
                self._acknowledge(character, request.cursor_from, request.snapshot.through_sequence)
            ids = tuple(s.signal_id for s in attention_changes) if not reason else ()
            decision = DeepDecision(request.request_id, note_result, compaction_result, not reason, reason or 'applied', ids)
            self._append(Event.create(character, 'deep.batch.completed' if not reason else 'deep.batch.rejected',
                {'fingerprint': fingerprint, 'decision': asdict(decision),
                 'attention_proposals': [asdict(p) for p in result.attention],
                 'cursor_from': request.cursor_from, 'through': request.snapshot.through_sequence}, event_id=audit_id))
            return decision

    def _acknowledge(self, character_id: CharacterId, expected: int, through: int) -> None:
        if not expected <= through <= self.high_watermark(character_id):
            raise ValueError("Invalid Deep cursor range")
        if self.cursor(character_id) != expected:
            raise ValueError("Deep cursor conflict")
        self._db.execute("UPDATE character_state SET deep_cursor=? WHERE character_id=?",
                         (through, character_id))

    def acknowledge(self, character_id: CharacterId, expected: int, through: int) -> None:
        with self._transaction():
            self._acknowledge(character_id, expected, through)

    def apply_note(self, proposal: NoteProposal, *, cursor_from: int | None = None) -> UpdateResult:
        with self._transaction():
            return self._apply_note(proposal, cursor_from=cursor_from)

    def _apply_note(self, proposal: NoteProposal, *, cursor_from: int | None = None) -> UpdateResult:
        encoded = canonical_json(asdict(proposal))
        audit_id = f"proposal_{proposal.proposal_id}"
        previous = self.get(audit_id)
        if previous:
            payload = previous.payload
            if payload.get("proposal") != encoded:
                raise EventConflict(f"proposal_id conflict: {proposal.proposal_id}")
            if cursor_from is not None and self.cursor(proposal.character_id) < proposal.observed_through_sequence:
                self._acknowledge(proposal.character_id, cursor_from, proposal.observed_through_sequence)
            return UpdateResult(payload["accepted"], payload["revision"], payload["reason"])
        state = self.snapshot(proposal.character_id)
        reason = self._validate_proposal(proposal)
        if not reason:
            try:
                state = reduce_note(state, proposal)
            except RevisionConflict:
                reason = "revision_conflict"
        accepted = not reason
        self._db.execute("INSERT OR IGNORE INTO character_state(character_id) VALUES (?)",
                         (proposal.character_id,))
        if accepted:
            self._db.execute("UPDATE character_state SET revision=?, context_note=? WHERE character_id=?",
                             (state.revision, state.context_note, state.character_id))
        result = UpdateResult(accepted, state.revision, reason or "applied")
        self._append(Event.create(proposal.character_id,
            "state.patch.applied" if accepted else "state.patch.rejected",
            {"proposal": encoded, **asdict(result)}, event_id=audit_id,
            causation_id=proposal.source_event_ids[-1] if proposal.source_event_ids else None))
        if cursor_from is not None:
            self._acknowledge(proposal.character_id, cursor_from, proposal.observed_through_sequence)
        return result

    def _validate_proposal(self, proposal: NoteProposal) -> str:
        if not isinstance(proposal.proposal_id, str) or not proposal.proposal_id.strip():
            return "invalid_proposal_id"
        if not isinstance(proposal.note, str) or not 1 <= len(proposal.note.strip()) <= 1000:
            return "invalid_note"
        if type(proposal.based_on_revision) is not int or proposal.based_on_revision < 0:
            return "invalid_revision"
        if type(proposal.observed_through_sequence) is not int:
            return "invalid_watermark"
        if not 0 < proposal.observed_through_sequence <= self.high_watermark(proposal.character_id):
            return "invalid_watermark"
        if not proposal.source_event_ids:
            return "missing_sources"
        for event_id in proposal.source_event_ids:
            source = self.get(event_id)
            if (source is None or source.character_id != proposal.character_id
                    or source.sequence > proposal.observed_through_sequence
                    or source.kind not in ("user.message.completed", "character.reply.completed")):
                return "invalid_source"
        return ""

    def unfinished_replies(self, character_id: CharacterId) -> tuple[Event, ...]:
        rows = self._db.execute("""SELECT * FROM events AS started WHERE character_id=?
            AND json_extract(content, '$.kind') = 'character.reply.started'
            AND NOT EXISTS (SELECT 1 FROM events AS ended
                WHERE ended.character_id=started.character_id
                AND json_extract(ended.content, '$.turn_id')=json_extract(started.content, '$.turn_id')
                AND json_extract(ended.content, '$.kind') IN
                    ('character.reply.completed', 'character.reply.cancelled', 'character.reply.failed'))
            ORDER BY sequence""", (character_id,)).fetchall()
        return tuple(self._decode(row) for row in rows)

    def unfinished_inputs(self, character_id: CharacterId) -> tuple[Event, ...]:
        rows = self._db.execute("""SELECT * FROM events AS input WHERE character_id=?
            AND json_extract(content, '$.kind') = 'user.message.completed'
            AND NOT EXISTS (SELECT 1 FROM events AS ended
                WHERE ended.character_id=input.character_id
                AND json_extract(ended.content, '$.turn_id')=json_extract(input.content, '$.turn_id')
                AND json_extract(ended.content, '$.kind') IN
                    ('character.reply.completed', 'character.reply.cancelled', 'character.reply.failed'))
            ORDER BY sequence""", (character_id,)).fetchall()
        return tuple(self._decode(row) for row in rows)
