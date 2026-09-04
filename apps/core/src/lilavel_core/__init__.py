"""Importable package boundary for Lilavel Core."""

from .runtime import (
    CancellationTimeout,
    EventQueueOverflow,
    GenerationFailed,
    GenerationHandle,
    GenerationResult,
    ModelRuntime,
    ModelRuntimeError,
    ProtocolViolation,
    RuntimeBusy,
    RuntimeHealth,
    RuntimeNotReady,
    RuntimeShuttingDown,
    RuntimeStartTimeout,
    ShutdownTimeout,
    SidecarCrashed,
)
from .sidecar_protocol import (
    ContextMessage,
    GenerationAccepted,
    GenerationCancelled,
    GenerationCompleted,
    GenerationEvent,
    HealthEvent,
    ModelRequest,
    ReadyEvent,
    ShutdownEvent,
    TextDelta,
)
from .sidecar_protocol import GenerationFailed as GenerationFailedEvent

__version__ = "0.1.0"

__all__ = [
    "GenerationAccepted",
    "GenerationCancelled",
    "GenerationCompleted",
    "GenerationEvent",
    "GenerationFailedEvent",
    "GenerationFailed",
    "GenerationHandle",
    "GenerationResult",
    "CancellationTimeout",
    "ContextMessage",
    "EventQueueOverflow",
    "HealthEvent",
    "ModelRequest",
    "ModelRuntime",
    "ModelRuntimeError",
    "ProtocolViolation",
    "RuntimeBusy",
    "RuntimeHealth",
    "RuntimeNotReady",
    "RuntimeStartTimeout",
    "RuntimeShuttingDown",
    "ReadyEvent",
    "ShutdownTimeout",
    "SidecarCrashed",
    "ShutdownEvent",
    "TextDelta",
    "__version__",
]
