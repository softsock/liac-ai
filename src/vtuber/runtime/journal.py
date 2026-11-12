"""SQLite transactions own event ordering, state, proposal decisions and Deep ack."""

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, replace
from pathlib import Path
from typing import Iterator

from vtuber.contracts.events import CharacterId, Event, canonical_json, utc_now
from vtuber.contracts.context import CompactionProposal, CompactionResult, ContextEpoch, ContextItem
from vtuber.contracts.state import CharacterState, FastSnapshot, NoteProposal, UpdateResult
from vtuber.runtime.state import RevisionConflict, reduce_note


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
        # Reject malformed identities before SQL binding or constructing audit IDs.
        for value in (proposal.proposal_id, proposal.character_id):
            if not isinstance(value, str) or not 1 <= len(value.strip()) <= 200:
                raise ValueError("Invalid compaction identity")
        encoded = canonical_json(asdict(proposal))
        with self._transaction():
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
