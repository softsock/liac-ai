"""Observable lifecycle and stale-event tests for ModelRuntime."""

import sys
from pathlib import Path

import pytest

from lilavel_core import (
    GenerationAccepted,
    GenerationCancelled,
    GenerationCompleted,
    ModelRequest,
    ModelRuntime,
    ProtocolViolation,
    RuntimeNotReady,
    RuntimeStartTimeout,
    SidecarCrashed,
    TextDelta,
)
from lilavel_core.sidecar_protocol import MAX_PROMPT_BYTES

FIXTURE = Path(__file__).parent / "fixtures" / "fake_sidecar.py"


def runtime(
    mode: str = "normal", *, startup_timeout: float = 30.0, write_timeout: float = 5.0
) -> ModelRuntime:
    return ModelRuntime(
        command=(sys.executable, str(FIXTURE), mode),
        sidecar_dir=Path(__file__).parents[1],
        startup_timeout=startup_timeout,
        write_timeout=write_timeout,
    )


def test_start_streams_events_and_shuts_down_cleanly() -> None:
    model = runtime()
    model.start()
    try:
        assert model.ready
        assert model.health().state == "ready"
        handle = model.generate(ModelRequest("stream"))
        result = handle.wait(2.0)
        events = list(handle)

        assert result.text == "streamed"
        assert [type(event) for event in events] == [
            GenerationAccepted,
            TextDelta,
            GenerationCompleted,
        ]
        assert model.health().state == "ready"
    finally:
        model.shutdown()

    assert model.health().state == "closed"


def test_cancel_waits_for_terminal_event_and_recovers_in_same_process() -> None:
    model = runtime("supersede-race")
    model.start()
    try:
        cancelled = model.generate(ModelRequest("cancel"))
        stream = iter(cancelled)
        assert isinstance(next(stream), GenerationAccepted)
        assert isinstance(next(stream), TextDelta)
        assert model.cancel(cancelled.generation_id)
        assert model.cancel(cancelled.generation_id)
        assert cancelled.wait(2.0).status == "cancelled"
        remaining = list(stream)
        assert any(isinstance(event, GenerationCancelled) for event in remaining)
        assert not any(
            isinstance(event, TextDelta) and event.delta == "STALE_LATE_DELTA"
            for event in remaining
        )
        recovery = model.generate(ModelRequest("recovery"))
        assert recovery.wait(2.0).text == "recovered"
        recovery_events = list(recovery)
        assert [event.delta for event in recovery_events if isinstance(event, TextDelta)] == [
            "recovered"
        ]
    finally:
        model.shutdown()


def test_unexpected_sidecar_death_fails_pending_generation() -> None:
    model = runtime("crash-after-accepted")
    model.start()
    handle = model.generate(ModelRequest("crash"))

    with pytest.raises(SidecarCrashed):
        handle.wait(2.0)
    assert model.health().state == "failed"
    with pytest.raises(RuntimeNotReady):
        model.generate(ModelRequest("not-reusable"))


def test_malformed_sidecar_output_fails_closed() -> None:
    model = runtime("malformed-after-accepted")
    model.start()
    handle = model.generate(ModelRequest("malformed"))

    with pytest.raises(ProtocolViolation):
        handle.wait(2.0)
    assert model.health().state == "failed"


def test_truncated_shutdown_frame_is_rejected_at_eof() -> None:
    """A partial frame during teardown remains a protocol failure."""

    model = runtime("shutdown-truncated")
    model.start()

    with pytest.raises(ProtocolViolation, match="invalid sidecar protocol: malformed"):
        model.shutdown()

    assert model.health().state == "failed"
    # Failed runtimes retain an idempotent, non-raising cleanup path.
    model.shutdown()


def test_startup_readiness_is_bounded() -> None:
    model = runtime("no-ready", startup_timeout=0.1)

    with pytest.raises(RuntimeStartTimeout):
        model.start()
    assert model.health().state == "failed"


def test_command_write_is_bounded_when_sidecar_stops_reading() -> None:
    model = runtime("no-read-after-ready", write_timeout=0.1)
    model.start()
    try:
        with pytest.raises(SidecarCrashed):
            model.generate(ModelRequest("x" * MAX_PROMPT_BYTES))
        assert model.health().state == "failed"
    finally:
        model.shutdown()
