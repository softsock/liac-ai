"""SQLite transactions own event ordering, state, proposal decisions and Deep ack."""

import json
import sqlite3
from hashlib import sha256
from contextlib import contextmanager
from dataclasses import asdict, replace
from pathlib import Path
from datetime import datetime, timedelta
from typing import Iterator

from vtuber.contracts.events import CharacterId, CharacterInitiative, Event, canonical_json, utc_now
from vtuber.contracts.context import CompactionProposal, CompactionResult, ContextEpoch, ContextItem
from vtuber.contracts.state import CharacterState, FastSnapshot, NoteProposal, UpdateResult
from vtuber.runtime.state import RevisionConflict, reduce_note
from vtuber.contracts.deep import (CompactionInput, DeepRequest, DeepResult, DeepDecision, evidence_ids,
    InitiativeProposal, InitiativeCancel, validate_initiative_timing)


class EventConflict(ValueError):
    """An idempotency identifier was reused with different content."""


class Journal:
    def __init__(self, path: str | Path) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        try:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=FULL")
            version = self._db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2):
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
                self._db.execute("PRAGMA user_version=2")
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
            raise

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
            if last_kind in ('user.message.completed', 'character.initiative.started'):
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

    def deep_request(self, character_id: str, *, request_id: str,
                     max_events: int = 100, compact: bool = False,
                     working_context_tokens: int = 2048, initiative_allowed: bool = False,
                     initiative_delay_seconds: float = 5.0, initiative_ttl_seconds: float = 120.0) -> DeepRequest | None:
        if max_events < 1 or not request_id.strip():
            raise ValueError('Invalid Deep request')
        with self._transaction():
            cursor = self.cursor(character_id)
            pending, safe, opened = [], 0, set()
            for row in self._db.execute('SELECT * FROM events WHERE character_id=? AND sequence>? ORDER BY sequence',
                                        (character_id, cursor)):
                event = self._decode(row)
                pending.append(event)
                if event.kind in ('user.message.completed', 'character.initiative.started'):
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
            autonomous = any(e.kind == 'character.initiative.started' for e in events)
            if events and not dialogue:
                if not autonomous:
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
            observed = tuple(e for e in events if not e.kind.startswith(('deep.', 'state.patch.', 'context.epoch.', 'initiative.')))
            return DeepRequest(request_id, snapshot, cursor, observed, compaction, working_context_tokens,
                initiative_allowed, utc_now() if initiative_allowed else '', initiative_delay_seconds, initiative_ttl_seconds)

    def apply_deep(self, request: DeepRequest, result: DeepResult, *,
                   compaction_error: str | None = None, context_error: str | None = None) -> DeepDecision:
        request_data = asdict(request)
        # Default omission preserves fingerprints of pre-Markdown schema-v1 batches.
        if request.working_context_tokens == 2048:
            del request_data['working_context_tokens']
        for key, default in dict(initiative_allowed=False, captured_at='',
                initiative_delay_seconds=5.0, initiative_ttl_seconds=120.0).items():
            if request_data[key] == default:
                del request_data[key]
        result_data = asdict(result)
        if result.initiative is None:
            del result_data['initiative']
        fingerprint_data = {'request': request_data, 'result': result_data,
                            'compaction_error': compaction_error}
        if context_error is not None:
            fingerprint_data['context_error'] = context_error
        fingerprint = sha256(canonical_json(fingerprint_data).encode()).hexdigest()
        character = request.snapshot.state.character_id
        audit_id = 'deep_' + request.request_id
        with self._transaction():
            previous = self.get(audit_id)
            if previous:
                payload = previous.payload
                if payload['fingerprint'] != fingerprint:
                    raise EventConflict('Deep request ID conflict')
                value = payload['decision']
                return DeepDecision(value['request_id'], UpdateResult(**value['note']) if value['note'] else None,
                    CompactionResult(**value['compaction']) if value['compaction'] else None,
                    value['acknowledged'], value['reason'], value.get('initiative_reason'))
            if result.request_id != request.request_id or type(result.schema_version) is not int or result.schema_version not in (1, 2):
                raise ValueError('Invalid Deep result envelope')
            if self.cursor(character) != request.cursor_from:
                raise ValueError('Deep cursor conflict')
            reason = ''
            state = self.snapshot(character)
            epoch = self.context_epoch(character)
            initiative_fresh = (request.snapshot.state.revision == state.revision
                                and request.snapshot.epoch.version == epoch.version)
            if result.note or result.compaction:
                if request.snapshot.state.revision != state.revision:
                    reason = 'revision_conflict'
            if (result.note or result.compaction) and request.snapshot.epoch.version != epoch.version:
                reason = reason or 'epoch_conflict'
            evidence = evidence_ids(request)
            if result.note:
                p = result.note
                if (p.proposal_id != request.request_id+':note' or p.character_id != character
                        or p.based_on_revision != request.snapshot.state.revision
                        or p.observed_through_sequence != request.snapshot.through_sequence
                        or not set(p.source_event_ids) <= evidence):
                    reason = reason or 'invalid_note_dependencies'
                reason = reason or context_error or self._validate_proposal(p)
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
                self._acknowledge(character, request.cursor_from, request.snapshot.through_sequence)
            initiative_reason = self._apply_initiative(request, result.initiative, fresh=initiative_fresh) if not reason else None
            decision = DeepDecision(request.request_id, note_result, compaction_result, not reason,
                reason or 'applied', initiative_reason)
            self._append(Event.create(character, 'deep.batch.completed' if not reason else 'deep.batch.rejected',
                {'fingerprint': fingerprint, 'decision': asdict(decision),
                 'cursor_from': request.cursor_from, 'through': request.snapshot.through_sequence}, event_id=audit_id))
            return decision

    def latest_user_sequence(self, character_id: str, through: int | None = None) -> int:
        return self._db.execute("""SELECT COALESCE(MAX(sequence),0) FROM events WHERE character_id=?
            AND sequence<=? AND json_extract(content,'$.kind')='user.message.completed'""",
            (character_id, through if through is not None else self.high_watermark(character_id))).fetchone()[0]

    def pending_initiative(self, character_id: str) -> Event | None:
        row = self._db.execute("""SELECT * FROM events AS p WHERE character_id=?
            AND json_extract(content,'$.kind')='initiative.proposed'
            AND NOT EXISTS (SELECT 1 FROM events AS c WHERE c.event_id='initiative_closed_' || p.event_id)
            ORDER BY sequence DESC LIMIT 1""", (character_id,)).fetchone()
        return self._decode(row) if row else None

    def _close_initiative(self, proposal_id: str, reason: str) -> None:
        proposal = self.get(proposal_id)
        if proposal is None or proposal.kind != 'initiative.proposed':
            raise ValueError('Unknown initiative')
        event_id = 'initiative_closed_' + proposal_id
        if self.get(event_id) is None:
            self._append(Event.create(proposal.character_id, 'initiative.closed',
                dict(proposal_id=proposal_id, reason=reason), event_id=event_id, causation_id=proposal_id))

    def close_initiative(self, proposal_id: str, reason: str) -> None:
        with self._transaction():
            self._close_initiative(proposal_id, reason)

    def last_initiative_attempt(self, character_id: str) -> Event | None:
        row = self._db.execute("""SELECT * FROM events WHERE character_id=?
            AND json_extract(content,'$.kind')='character.initiative.started'
            ORDER BY sequence DESC LIMIT 1""", (character_id,)).fetchone()
        return self._decode(row) if row else None

    def initiative_attempted(self, character_id: str, anchor: int) -> bool:
        return self._db.execute("""SELECT 1 FROM events AS i JOIN events AS p
            ON p.event_id=json_extract(i.content,'$.payload.proposal_id')
            WHERE i.character_id=? AND json_extract(i.content,'$.kind')='character.initiative.started'
            AND json_extract(p.content,'$.payload.anchor')=? LIMIT 1""", (character_id, anchor)).fetchone() is not None

    def _apply_initiative(self, request: DeepRequest, proposal: InitiativeProposal | InitiativeCancel | None,
                          *, fresh: bool) -> str:
        if proposal is None:
            return 'unchanged'
        character = request.snapshot.state.character_id
        anchor = self.latest_user_sequence(character, request.snapshot.through_sequence)
        if not fresh or not anchor or anchor != self.latest_user_sequence(character):
            return 'stale'
        pending = self.pending_initiative(character)
        if pending and pending.sequence > request.snapshot.through_sequence:
            return 'stale'
        if isinstance(proposal, InitiativeCancel):
            if pending:
                self._close_initiative(pending.event_id, 'luna_cancelled: '+proposal.reason)
            return 'cancelled'
        if not isinstance(proposal, InitiativeProposal):
            raise ValueError('Invalid initiative proposal')
        if not request.initiative_allowed:
            return 'disabled'
        if self.initiative_attempted(character, anchor):
            return 'duplicate'
        for source_id in proposal.source_event_ids:
            source = self.get(source_id)
            if (source_id not in evidence_ids(request) or source is None or source.character_id != character
                    or source.sequence > request.snapshot.through_sequence
                    or source.kind not in ('user.message.completed', 'character.reply.completed')):
                raise ValueError('Invalid initiative evidence')
        delay = proposal.delay_seconds if proposal.delay_seconds is not None else request.initiative_delay_seconds
        ttl = proposal.ttl_seconds if proposal.ttl_seconds is not None else request.initiative_ttl_seconds
        validate_initiative_timing(delay, ttl)
        captured = datetime.fromisoformat(request.captured_at)
        if captured.tzinfo is None:
            raise ValueError('Initiative capture must be timezone-aware')
        expires = captured + timedelta(seconds=ttl)
        if datetime.fromisoformat(utc_now()) >= expires:
            return 'expired'
        key = sha256(canonical_json([proposal.intent.strip().casefold(), sorted(proposal.source_event_ids)]).encode()).hexdigest()
        if self._db.execute("""SELECT 1 FROM events WHERE character_id=?
            AND json_extract(content,'$.kind')='initiative.proposed'
            AND json_extract(content,'$.payload.duplicate_key')=? LIMIT 1""", (character, key)).fetchone():
            return 'duplicate'
        if pending:
            self._close_initiative(pending.event_id, 'replaced')
        self._append(Event.create(character, 'initiative.proposed',
            dict(intent=proposal.intent, reason=proposal.reason, source_event_ids=proposal.source_event_ids,
                anchor=anchor, revision=self.snapshot(character).revision, epoch=self.context_epoch(character).version,
                ready_at=(captured+timedelta(seconds=delay)).isoformat(), expires_at=expires.isoformat(),
                duplicate_key=key), event_id='initiative_'+request.request_id, occurred_at=request.captured_at))
        return 'accepted'

    def claim_initiative(self, proposal_id: str, snapshot: FastSnapshot, *, cooldown_seconds: float = 0,
                         checked_at: str | None = None) -> CharacterInitiative | None:
        with self._transaction():
            proposal = self.pending_initiative(snapshot.state.character_id)
            if proposal is None or proposal.event_id != proposal_id:
                return None
            p = proposal.payload
            # Runtime projects its arming UTC anchor with monotonic elapsed time.
            now = datetime.fromisoformat(checked_at if checked_at is not None else utc_now())
            if now.tzinfo is None:
                raise ValueError('Initiative check must be timezone-aware')
            reason = None
            if now >= datetime.fromisoformat(p['expires_at']):
                reason = 'expired'
            elif (p['anchor'] != self.latest_user_sequence(proposal.character_id)
                    or p['revision'] != self.snapshot(proposal.character_id).revision
                    or p['epoch'] != self.context_epoch(proposal.character_id).version
                    or snapshot.state != self.snapshot(proposal.character_id)
                    or snapshot.epoch != self.context_epoch(proposal.character_id)
                    or snapshot.through_sequence != self.high_watermark(proposal.character_id)):
                reason = 'stale'
            elif self.initiative_attempted(proposal.character_id, p['anchor']):
                reason = 'duplicate'
            if reason:
                self._close_initiative(proposal_id, reason)
                return None
            if now < datetime.fromisoformat(p['ready_at']) or self.unfinished_inputs(proposal.character_id):
                return None
            last = self.last_initiative_attempt(proposal.character_id)
            if last and (now - datetime.fromisoformat(last.occurred_at)).total_seconds() < cooldown_seconds:
                return None
            message = CharacterInitiative(p['intent'], p['reason'], proposal.character_id,
                'initiative_input_'+proposal_id, 'initiative_turn_'+proposal_id, utc_now(), proposal_id)
            self._close_initiative(proposal_id, 'claimed')
            self._append(message.as_event())
            self._append(Event.create(proposal.character_id, 'character.reply.started',
                dict(snapshot_revision=snapshot.state.revision, through_sequence=snapshot.through_sequence,
                     epoch_version=snapshot.epoch.version,
                     compacted_through_sequence=snapshot.epoch.compacted_through_sequence),
                event_id='reply_started_'+message.event_id, turn_id=message.turn_id, causation_id=message.event_id))
            return message

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
        unchanged = accepted and state.revision == proposal.based_on_revision
        if accepted and not unchanged:
            self._db.execute("UPDATE character_state SET revision=?, context_note=? WHERE character_id=?",
                             (state.revision, state.context_note, state.character_id))
        result = UpdateResult(accepted, state.revision, reason or ("no_change" if unchanged else "applied"))
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
        if not isinstance(proposal.note, str) or len(proposal.note.encode("utf-8")) > 32768:
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
            AND json_extract(content, '$.kind') IN ('user.message.completed', 'character.initiative.started')
            AND NOT EXISTS (SELECT 1 FROM events AS ended
                WHERE ended.character_id=input.character_id
                AND json_extract(ended.content, '$.turn_id')=json_extract(input.content, '$.turn_id')
                AND json_extract(ended.content, '$.kind') IN
                    ('character.reply.completed', 'character.reply.cancelled', 'character.reply.failed'))
            ORDER BY sequence""", (character_id,)).fetchall()
        return tuple(self._decode(row) for row in rows)
