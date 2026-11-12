"""Optional local developer observations, separate from domain events."""
import logging
from typing import Callable

TraceSink = Callable[[str, str, dict[str, object]], None]


def trace_enabled(sink: TraceSink | None) -> bool:
    try:
        return sink is not None and not getattr(sink, 'error', None)
    except Exception:
        return False


def emit_trace(sink: TraceSink | None, kind: str, request_id: str, **data: object) -> None:
    if trace_enabled(sink):
        try:
            sink(kind, request_id, data)
        except Exception as error:
            logging.getLogger(__name__).warning('Trace capture failed: %s', type(error).__name__)
