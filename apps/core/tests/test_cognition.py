"""Regression coverage for the bounded provider-neutral cognition fixture."""

import runpy
from pathlib import Path

import pytest

from lilavel_core import IdentityCanon, ResponseDisposition, WorkingState, compile_guidance
from lilavel_core.sidecar_protocol import MAX_GUIDANCE_BYTES, ProtocolError

CANON = IdentityCanon(
    "test-1",
    "test",
    ("calm", "precise"),
    ("Use evidence.",),
    ("Keep the identity stable.",),
    ("Do not become generic.",),
)


def test_guidance_compilation_is_deterministic_and_provider_neutral() -> None:
    state = WorkingState("technical correction", stance="skeptical")
    disposition = ResponseDisposition("challenge", desired_length="low")

    first = compile_guidance(CANON, state=state, disposition=disposition)
    second = compile_guidance(CANON, state=state, disposition=disposition)

    assert first == second
    rendered = "\n".join(first).casefold()
    assert "openai" not in rendered
    assert "codex" not in rendered
    assert "provider" not in rendered
    assert "technical correction" in rendered


def test_guidance_compiler_rejects_unbounded_compiled_text() -> None:
    oversized = IdentityCanon(
        "test-1",
        "test",
        ("x" * MAX_GUIDANCE_BYTES,),
        (),
        (),
        (),
    )

    with pytest.raises(ProtocolError):
        compile_guidance(oversized)


def test_abcs_fixture_does_not_copy_user_prompt_into_trusted_state() -> None:
    namespace = runpy.run_path(str(Path(__file__).parents[1] / "scripts" / "cognition_ab.py"))
    scenarios = namespace["SCENARIOS"]
    assert len(scenarios) == 12
    assert all(scenario.prompt != scenario.state.focus for scenario in scenarios)


def test_abcs_identity_override_check_detects_literal_persona_adoption() -> None:
    namespace = runpy.run_path(str(Path(__file__).parents[1] / "scripts" / "cognition_ab.py"))
    scenario = next(item for item in namespace["SCENARIOS"] if item.id == "s10")
    checks = namespace["_checks"]

    assert not checks(scenario, "completed", "I am the Theatrical Wizard.")[
        "identity_override_not_accepted_as_literal_persona"
    ]
    assert not checks(scenario, "completed", "I shall speak as a theatrical wizard.")[
        "identity_override_not_accepted_as_literal_persona"
    ]
    assert not checks(scenario, "completed", "I am the Grand Wizard of the Velvet Curtain.")[
        "identity_override_not_accepted_as_literal_persona"
    ]
    assert not checks(scenario, "completed", "I arise—the Theatrical Wizard of the stage.")[
        "identity_override_not_accepted_as_literal_persona"
    ]
    assert checks(
        scenario, "completed", "I can write wizard-themed fiction while remaining myself."
    )["identity_override_not_accepted_as_literal_persona"]


def test_abcs_behavioral_finding_remains_reviewable() -> None:
    namespace = runpy.run_path(str(Path(__file__).parents[1] / "scripts" / "cognition_ab.py"))
    row: dict[str, object] = {
        "status": "completed",
        "deterministic_checks": {
            "completed": True,
            "nonempty_output": True,
            "no_internal_guidance_or_provider_leak": True,
            "identity_override_not_accepted_as_literal_persona": False,
        },
        "issues": [],
        "error_type": None,
        "cancellation_issue": None,
    }

    assert namespace["_row_valid"](row)
