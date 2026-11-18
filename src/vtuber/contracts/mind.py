from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol


class MindStreamError(RuntimeError):
    """Adapter failure with a technical code safe for runtime diagnostics."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class MindDecision:
    action: Literal["speak", "stay_silent"]
    message: str = ""
    tool_call_id: str = ""
    usage: dict[str, int] | None = None

    def __post_init__(self) -> None:
        if self.action == "speak" and self.message.strip():
            return
        if self.action == "stay_silent" and not self.message:
            return
        raise ValueError("Invalid single-mind action or message")


class SingleMindPort(Protocol):
    async def generate(
        self,
        messages: tuple[dict[str, object], ...],
        *,
        on_speak_delta: Callable[[str], None] | None = None,
    ) -> MindDecision:
        ...
