"""Typed version-one JSONL messages shared with the model sidecar."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Final, Literal, cast

PROTOCOL_VERSION: Final = 1
MAX_FRAME_BYTES: Final = 256 * 1024
MAX_PROMPT_BYTES: Final = 64 * 1024
MAX_DELTA_BYTES: Final = 16 * 1024
MAX_RESPONSE_BYTES: Final = 256 * 1024
MAX_ID_BYTES: Final = 128
MAX_EPOCH: Final = 2**53 - 1

type ProtocolErrorCode = Literal[
    "busy",
    "not_ready",
    "closed",
    "not_active",
    "startup_error",
    "provider_error",
    "unsupported_output",
    "protocol_error",
    "output_limit",
    "cancelled",
    "cleanup_timeout",
    "cleanup_error",
    "shutdown_timeout",
    "cancellation_timeout",
]

type RuntimeState = Literal[
    "new",
    "starting",
    "ready",
    "busy",
    "shutting_down",
    "failed",
    "closed",
]
type HealthState = Literal["starting", "ready", "busy", "failed", "closed"]
type GenerationStatus = Literal["completed", "cancelled"]


class ProtocolError(ValueError):
    """Raised when a JSONL frame is not a valid version-one protocol message."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class ModelRequest:
    """The intentionally small Core-owned request sent to the model boundary."""

    prompt: str

    def __post_init__(self) -> None:
        _bounded_string(self.prompt, MAX_PROMPT_BYTES, "prompt")


@dataclass(frozen=True, slots=True)
class GenerateCommand:
    generation_id: str
    epoch: int
    prompt: str


@dataclass(frozen=True, slots=True)
class CancelCommand:
    generation_id: str
    epoch: int


@dataclass(frozen=True, slots=True)
class HealthCommand:
    pass


@dataclass(frozen=True, slots=True)
class ShutdownCommand:
    pass


type ProtocolCommand = GenerateCommand | CancelCommand | HealthCommand | ShutdownCommand


@dataclass(frozen=True, slots=True)
class ReadyEvent:
    provider: str
    model_id: str
    api: str


@dataclass(frozen=True, slots=True)
class HealthEvent:
    state: HealthState


@dataclass(frozen=True, slots=True)
class GenerationAccepted:
    generation_id: str
    epoch: int


@dataclass(frozen=True, slots=True)
class TextDelta:
    generation_id: str
    epoch: int
    delta: str


@dataclass(frozen=True, slots=True)
class GenerationCompleted:
    generation_id: str
    epoch: int


@dataclass(frozen=True, slots=True)
class GenerationCancelled:
    generation_id: str
    epoch: int


@dataclass(frozen=True, slots=True)
class GenerationFailed:
    generation_id: str | None
    epoch: int | None
    code: ProtocolErrorCode


@dataclass(frozen=True, slots=True)
class ShutdownEvent:
    pass


type GenerationEvent = (
    ReadyEvent
    | HealthEvent
    | GenerationAccepted
    | TextDelta
    | GenerationCompleted
    | GenerationCancelled
    | GenerationFailed
    | ShutdownEvent
)


def encode_command(command: ProtocolCommand) -> bytes:
    if isinstance(command, GenerateCommand):
        _id(command.generation_id)
        _epoch(command.epoch)
        _bounded_string(command.prompt, MAX_PROMPT_BYTES, "prompt")
        value: dict[str, object] = {
            "protocol_version": PROTOCOL_VERSION,
            "type": "generate",
            "generation_id": command.generation_id,
            "epoch": command.epoch,
            "prompt": command.prompt,
        }
    elif isinstance(command, CancelCommand):
        _id(command.generation_id)
        _epoch(command.epoch)
        value = {
            "protocol_version": PROTOCOL_VERSION,
            "type": "cancel",
            "generation_id": command.generation_id,
            "epoch": command.epoch,
        }
    elif isinstance(command, HealthCommand):
        value = {"protocol_version": PROTOCOL_VERSION, "type": "health"}
    else:
        value = {"protocol_version": PROTOCOL_VERSION, "type": "shutdown"}
    return _encode_frame(value)


def encode_event(event: GenerationEvent) -> bytes:
    if isinstance(event, ReadyEvent):
        value: dict[str, object] = {
            "protocol_version": PROTOCOL_VERSION,
            "type": "ready",
            "provider": _bounded_string(event.provider, MAX_ID_BYTES, "provider"),
            "model_id": _bounded_string(event.model_id, MAX_ID_BYTES, "model_id"),
            "api": _bounded_string(event.api, MAX_ID_BYTES, "api"),
        }
    elif isinstance(event, HealthEvent):
        _health_state(event.state)
        value = {"protocol_version": PROTOCOL_VERSION, "type": "health", "state": event.state}
    elif isinstance(event, GenerationAccepted):
        value = _generation_value("accepted", event.generation_id, event.epoch)
    elif isinstance(event, TextDelta):
        _id(event.generation_id)
        _epoch(event.epoch)
        _bounded_string(event.delta, MAX_DELTA_BYTES, "delta")
        if not event.delta:
            raise ProtocolError("invalid_field")
        value = _generation_value("text_delta", event.generation_id, event.epoch)
        value["delta"] = event.delta
    elif isinstance(event, GenerationCompleted):
        value = _generation_value("completed", event.generation_id, event.epoch)
    elif isinstance(event, GenerationCancelled):
        value = _generation_value("cancelled", event.generation_id, event.epoch)
    elif isinstance(event, GenerationFailed):
        _error_code(event.code)
        if (event.generation_id is None) != (event.epoch is None):
            raise ProtocolError("invalid_field")
        value = {"protocol_version": PROTOCOL_VERSION, "type": "failed", "code": event.code}
        if event.generation_id is not None and event.epoch is not None:
            _id(event.generation_id)
            _epoch(event.epoch)
            value["generation_id"] = event.generation_id
            value["epoch"] = event.epoch
    else:
        value = {"protocol_version": PROTOCOL_VERSION, "type": "shutdown"}
    return _encode_frame(value)


def parse_event(payload: bytes | str) -> GenerationEvent:
    value = _parse_object(payload)
    _require_keys(value, "protocol_version", "type")
    _version(value)
    event_type = value["type"]
    if not isinstance(event_type, str):
        raise ProtocolError("invalid_field")

    if event_type == "ready":
        _expect_keys(value, "protocol_version", "type", "provider", "model_id", "api")
        return ReadyEvent(
            _bounded_string(value["provider"], MAX_ID_BYTES, "provider"),
            _bounded_string(value["model_id"], MAX_ID_BYTES, "model_id"),
            _bounded_string(value["api"], MAX_ID_BYTES, "api"),
        )
    if event_type == "health":
        _expect_keys(value, "protocol_version", "type", "state")
        state = value["state"]
        if not isinstance(state, str):
            raise ProtocolError("invalid_field")
        _health_state(state)
        return HealthEvent(cast(HealthState, state))
    if event_type in {"accepted", "completed", "cancelled"}:
        _expect_keys(value, "protocol_version", "type", "generation_id", "epoch")
        generation_id = _id(value["generation_id"])
        epoch = _epoch(value["epoch"])
        if event_type == "accepted":
            return GenerationAccepted(generation_id, epoch)
        if event_type == "completed":
            return GenerationCompleted(generation_id, epoch)
        return GenerationCancelled(generation_id, epoch)
    if event_type == "text_delta":
        _expect_keys(value, "protocol_version", "type", "generation_id", "epoch", "delta")
        delta = _bounded_string(value["delta"], MAX_DELTA_BYTES, "delta")
        if not delta:
            raise ProtocolError("invalid_field")
        return TextDelta(_id(value["generation_id"]), _epoch(value["epoch"]), delta)
    if event_type == "failed":
        has_id = "generation_id" in value or "epoch" in value
        if has_id:
            _expect_keys(value, "protocol_version", "type", "generation_id", "epoch", "code")
            generation_id: str | None = _id(value["generation_id"])
            epoch: int | None = _epoch(value["epoch"])
        else:
            _expect_keys(value, "protocol_version", "type", "code")
            generation_id = None
            epoch = None
        code = value["code"]
        _error_code(code)
        return GenerationFailed(generation_id, epoch, cast(ProtocolErrorCode, code))
    if event_type == "shutdown":
        _expect_keys(value, "protocol_version", "type")
        return ShutdownEvent()
    raise ProtocolError("invalid_field")


def parse_command(payload: bytes | str) -> ProtocolCommand:
    value = _parse_object(payload)
    _require_keys(value, "protocol_version", "type")
    _version(value)
    command_type = value["type"]
    if not isinstance(command_type, str):
        raise ProtocolError("invalid_field")
    if command_type == "generate":
        _expect_keys(value, "protocol_version", "type", "generation_id", "epoch", "prompt")
        return GenerateCommand(
            _id(value["generation_id"]),
            _epoch(value["epoch"]),
            _bounded_string(value["prompt"], MAX_PROMPT_BYTES, "prompt"),
        )
    if command_type == "cancel":
        _expect_keys(value, "protocol_version", "type", "generation_id", "epoch")
        return CancelCommand(_id(value["generation_id"]), _epoch(value["epoch"]))
    if command_type == "health":
        _expect_keys(value, "protocol_version", "type")
        return HealthCommand()
    if command_type == "shutdown":
        _expect_keys(value, "protocol_version", "type")
        return ShutdownCommand()
    raise ProtocolError("invalid_field")


def _generation_value(event_type: str, generation_id: str, epoch: int) -> dict[str, object]:
    _id(generation_id)
    _epoch(epoch)
    return {
        "protocol_version": PROTOCOL_VERSION,
        "type": event_type,
        "generation_id": generation_id,
        "epoch": epoch,
    }


def _parse_object(payload: bytes | str) -> dict[str, object]:
    if isinstance(payload, bytes):
        if len(payload) > MAX_FRAME_BYTES:
            raise ProtocolError("frame_too_large")
    else:
        if len(payload.encode("utf-8")) > MAX_FRAME_BYTES:
            raise ProtocolError("frame_too_large")
    try:
        value = json.loads(payload, object_pairs_hook=_pairs)
    except ProtocolError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as error:
        raise ProtocolError("malformed") from error
    if not isinstance(value, dict):
        raise ProtocolError("malformed")
    return cast(dict[str, object], value)


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError("duplicate_field")
        result[key] = value
    return result


def _encode_frame(value: dict[str, object]) -> bytes:
    try:
        line = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(
            "utf-8"
        )
    except (TypeError, ValueError) as error:
        raise ProtocolError("invalid_field") from error
    if len(line) > MAX_FRAME_BYTES:
        raise ProtocolError("frame_too_large")
    return line + b"\n"


def _expect_keys(value: dict[str, object], *expected: str) -> None:
    if set(value) != set(expected):
        raise ProtocolError("unknown_field")


def _require_keys(value: dict[str, object], *required: str) -> None:
    if any(key not in value for key in required):
        raise ProtocolError("unknown_field")


def _version(value: dict[str, object]) -> None:
    version = value["protocol_version"]
    if type(version) is not int or version != PROTOCOL_VERSION:
        raise ProtocolError("unsupported_version")


def _id(value: object) -> str:
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > MAX_ID_BYTES:
        raise ProtocolError("invalid_field")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        raise ProtocolError("invalid_field")
    return value


def _epoch(value: object) -> int:
    if type(value) is not int or value < 0 or value > MAX_EPOCH:
        raise ProtocolError("invalid_field")
    return value


def _bounded_string(value: object, maximum: int, field: str) -> str:
    if not isinstance(value, str) or len(value.encode("utf-8")) > maximum:
        raise ProtocolError(f"invalid_{field}")
    return value


def _health_state(value: object) -> None:
    if value not in {"starting", "ready", "busy", "failed", "closed"}:
        raise ProtocolError("invalid_field")


def _error_code(value: object) -> None:
    if value not in {
        "busy",
        "not_ready",
        "closed",
        "not_active",
        "startup_error",
        "provider_error",
        "unsupported_output",
        "protocol_error",
        "output_limit",
        "cancelled",
        "cleanup_timeout",
        "cleanup_error",
        "shutdown_timeout",
        "cancellation_timeout",
    }:
        raise ProtocolError("invalid_field")
