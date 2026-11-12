"""SQLite transactions own event ordering, state, proposal decisions and Deep ack."""

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, replace
from pathlib import Path
from typing import Iterator

from vtuber.contracts.events import CharacterId, Event, canonical_json, utc_now
from vtuber.contracts.state import CharacterState, NoteProposal, UpdateResult
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
            if version not in (0, 1):
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
                self._db.execute("PRAGMA user_version=1")
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
