"""Deterministic coverage for the version-two sidecar wire contract."""

import json

import pytest

from lilavel_core.sidecar_protocol import (
    MAX_CONTEXT_BYTES,
    MAX_FRAME_BYTES,
    MAX_GUIDANCE_BLOCKS,
    MAX_GUIDANCE_BYTES,
    MAX_PROMPT_BYTES,
    CancelCommand,
    ContextMessage,
    GenerateCommand,
    GenerationAccepted,
    GenerationCancelled,
    GenerationCompleted,
    GenerationFailed,
    HealthCommand,
    HealthEvent,
    ModelRequest,
    ProtocolError,
    ReadyEvent,
    ShutdownCommand,
    ShutdownEvent,
    TextDelta,
    encode_command,
    encode_event,
    parse_command,
    parse_event,
)


def test_command_round_trip_keeps_small_request_shape() -> None:
    command = GenerateCommand("generation-1", 7, "Reply exactly OK.")

    assert parse_command(encode_command(command)) == command
    assert json.loads(encode_command(command)) == {
        "protocol_version": 2,
        "type": "generate",
        "generation_id": "generation-1",
        "epoch": 7,
        "prompt": "Reply exactly OK.",
    }


def test_structured_context_round_trip_contains_only_role_and_text() -> None:
    messages = (
        ContextMessage("user", "Remember the word quartz."),
        ContextMessage("assistant", "ACK_1"),
        ContextMessage("user", "What was the word?"),
    )
    command = GenerateCommand("generation-structured", 8, messages=messages)

    assert parse_command(encode_command(command)) == command
    assert json.loads(encode_command(command)) == {
        "protocol_version": 2,
        "type": "generate",
        "generation_id": "generation-structured",
        "epoch": 8,
        "messages": [
            {"role": "user", "text": "Remember the word quartz."},
            {"role": "assistant", "text": "ACK_1"},
            {"role": "user", "text": "What was the word?"},
        ],
    }


def test_guidance_round_trip_is_optional_and_messages_only_shape_stays_small() -> None:
    messages = (ContextMessage("user", "hello"),)
    baseline = GenerateCommand("generation-baseline", 1, messages=messages)
    guided = GenerateCommand(
        "generation-guided",
        2,
        messages=messages,
        system_prompt=("trusted identity", "trusted behavior"),
    )

    assert json.loads(encode_command(baseline)) == {
        "protocol_version": 2,
        "type": "generate",
        "generation_id": "generation-baseline",
        "epoch": 1,
        "messages": [{"role": "user", "text": "hello"}],
    }
    assert parse_command(encode_command(guided)) == guided
    assert json.loads(encode_command(guided))["system_prompt"] == [
        "trusted identity",
        "trusted behavior",
    ]


def test_guidance_rejects_malformed_empty_duplicate_and_unbounded_blocks() -> None:
    messages = (ContextMessage("user", "hello"),)
    with pytest.raises(ProtocolError):
        ModelRequest(messages=messages, system_prompt=("",))
    with pytest.raises(ProtocolError):
        ModelRequest(messages=messages, system_prompt=("same", "same"))
    with pytest.raises(ProtocolError):
        ModelRequest(messages=messages, system_prompt=("x",) * (MAX_GUIDANCE_BLOCKS + 1))
    with pytest.raises(ProtocolError):
        ModelRequest(messages=messages, system_prompt=("x" * (MAX_GUIDANCE_BYTES + 1),))
    with pytest.raises(ProtocolError):
        ModelRequest(messages=messages, system_prompt="not-a-block-list")  # type: ignore[arg-type]

    with pytest.raises(ProtocolError):
        parse_command(
            b'{"protocol_version":2,"type":"generate","generation_id":"x","epoch":1,'
            b'"messages":[{"role":"user","text":"hello"}],"system_prompt":[" "]}\n'
        )


def test_structured_context_rejects_unsupported_roles_and_unbounded_context() -> None:
    with pytest.raises(ProtocolError):
        parse_command(
            b'{"protocol_version":2,"type":"generate","generation_id":"x","epoch":1,'
            b'"messages":[{"role":"developer","text":"not supported"}]}\n'
        )

    with pytest.raises(ProtocolError):
        ModelRequest(messages=(ContextMessage("user", "x" * (MAX_CONTEXT_BYTES + 1)),))

    with pytest.raises(ProtocolError):
        ModelRequest(messages=())


def test_structured_context_cannot_mix_legacy_prompt() -> None:
    with pytest.raises(ProtocolError):
        GenerateCommand(
            "generation-1", 1, prompt="prompt", messages=(ContextMessage("user", "text"),)
        )


def test_all_event_variants_serialize_and_parse() -> None:
    events = [
        ReadyEvent("openai-codex", "gpt-5.6-luna", "openai-codex-responses"),
        HealthEvent("ready"),
        GenerationAccepted("generation-1", 1),
        TextDelta("generation-1", 1, "first"),
        GenerationCompleted("generation-1", 1),
        GenerationCancelled("generation-2", 2),
        GenerationFailed("generation-3", 3, "provider_error"),
        GenerationFailed(None, None, "startup_error"),
        ShutdownEvent(),
    ]

    assert [parse_event(encode_event(event)) for event in events] == events


@pytest.mark.parametrize(
    "payload",
    [
        b"not-json\n",
        b"[]\n",
        b'{"protocol_version":2,"type":"health","extra":true}\n',
        b'{"protocol_version":1,"type":"health"}\n',
        b'{"protocol_version":3,"type":"health"}\n',
        b'{"protocol_version":2,"type":"generate","generation_id":"x","epoch":1,"prompt":"x","generation_id":"y"}\n',
        b'{"protocol_version":2,"type":"text_delta","generation_id":"x","epoch":1,"delta":""}\n',
    ],
)
def test_malformed_or_unknown_frames_are_rejected(payload: bytes) -> None:
    with pytest.raises(ProtocolError):
        parse_event(payload)


def test_parser_rejects_non_integer_protocol_numbers() -> None:
    with pytest.raises(ProtocolError):
        parse_command(b'{"protocol_version":2.0,"type":"health"}\n')
    with pytest.raises(ProtocolError):
        parse_command(
            b'{"protocol_version":2,"type":"generate","generation_id":"x",'
            b'"epoch":1.0,"prompt":"x"}\n'
        )


def test_command_parser_rejects_oversized_prompt_and_frame() -> None:
    with pytest.raises(ProtocolError):
        ModelRequest("x" * (MAX_PROMPT_BYTES + 1))

    oversized = b"{" + b'"x":' + b'"' + b"x" * MAX_FRAME_BYTES + b'"}'
    with pytest.raises(ProtocolError):
        parse_command(oversized)


def test_command_variants_have_no_extra_semantics() -> None:
    assert parse_command(encode_command(CancelCommand("generation-1", 1))) == CancelCommand(
        "generation-1", 1
    )
    assert isinstance(parse_command(encode_command(HealthCommand())), HealthCommand)
    assert isinstance(parse_command(encode_command(ShutdownCommand())), ShutdownCommand)
