"""Deterministic Stage A availability reporting."""

from __future__ import annotations

import asyncio

import pytest

from lilavel_discord_edge import run_transport_probe


def test_transport_probe_is_explicitly_blocked_without_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # pytest's monkeypatch fixture is intentionally kept at the test boundary;
    # the probe itself only reads the namespaced environment variable.
    monkeypatch.delenv("LILAVEL_DISCORD_BOT_TOKEN", raising=False)

    report = asyncio.run(run_transport_probe(timeout_s=0.1))

    assert report == {
        "status": "BLOCKED",
        "reason": "missing LILAVEL_DISCORD_BOT_TOKEN",
        "live_probe": False,
    }
