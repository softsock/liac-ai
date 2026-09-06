"""Small provider-neutral cognition fixtures and deterministic guidance compiler."""

from dataclasses import dataclass
from typing import Literal

from .sidecar_protocol import MAX_GUIDANCE_BLOCKS, MAX_GUIDANCE_BYTES, ProtocolError

Aim = Literal[
    "answer",
    "acknowledge",
    "clarify",
    "challenge",
    "tease",
    "comfort",
    "disagree",
    "explore",
    "close",
]
Level = Literal["low", "normal", "high"]
Stance = Literal["neutral", "curious", "skeptical", "playful", "supportive"]


@dataclass(frozen=True, slots=True)
class IdentityCanon:
    version: str
    id: str
    traits: tuple[str, ...]
    principles: tuple[str, ...]
    boundaries: tuple[str, ...]
    anti_patterns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class WorkingState:
    focus: str
    engagement: Level = "normal"
    stance: Stance = "neutral"


@dataclass(frozen=True, slots=True)
class ResponseDisposition:
    aim: Aim = "answer"
    directness: Level = "normal"
    desired_length: Level = "normal"
    humor_allowed: bool = False
    question_policy: Literal["avoid", "required", "invite"] = "avoid"
    initiative: Level = "normal"


def compile_guidance(
    identity: IdentityCanon,
    *,
    state: WorkingState | None = None,
    disposition: ResponseDisposition | None = None,
) -> tuple[str, ...]:
    blocks = [
        "[Identity]\n" + "\n".join((*identity.traits, *identity.principles)),
        "[Boundaries]\n" + "\n".join((*identity.boundaries, *identity.anti_patterns)),
    ]
    if state is not None or disposition is not None:
        s = state or WorkingState("")
        d = disposition or ResponseDisposition()
        blocks.append(
            "[Current behavior]\n"
            + "\n".join(
                (
                    f"focus: {s.focus}",
                    f"engagement: {s.engagement}",
                    f"stance: {s.stance}",
                    f"aim: {d.aim}",
                    f"directness: {d.directness}",
                    f"desired density: {d.desired_length}",
                    f"humor: {'allowed' if d.humor_allowed else 'disallowed'}",
                    f"question policy: {d.question_policy}",
                    f"initiative: {d.initiative}",
                )
            )
        )
    result = tuple(blocks)
    if len(result) > MAX_GUIDANCE_BLOCKS or any(not block.strip() for block in result):
        raise ProtocolError("invalid_field")
    if len(set(result)) != len(result):
        raise ProtocolError("invalid_field")
    if sum(len(block.encode("utf-8")) for block in result) > MAX_GUIDANCE_BYTES:
        raise ProtocolError("invalid_field")
    return result
