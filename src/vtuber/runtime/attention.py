"""Small, deterministic wake policy and temporary sensory context."""

from time import monotonic

from vtuber.contracts.perception import Perception, PerceptionBatch


def should_wake(batch: PerceptionBatch) -> bool:
    """Only addressed direct input wakes Luna in M6.1a."""
    return any(item.delivery == 'direct' for item in batch.items)


class LiveState:
    """Last ambient observation per source and kind, scoped to one conversation."""

    def __init__(self, *, ttl_seconds: float = 120.0, max_items: int = 8) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_items = max_items
        self._items: dict[tuple[str, str, str], tuple[float, Perception]] = {}

    def observe(self, items: tuple[Perception, ...], *, now: float | None = None) -> None:
        instant = monotonic() if now is None else now
        self._expire(instant)
        for item in items:
            if item.delivery != 'ambient' or item.kind not in ('state', 'observation'):
                continue
            key = item.conversation_key, item.source, item.kind
            self._items.pop(key, None)
            self._items[key] = instant, item
        while len(self._items) > self.max_items:
            del self._items[next(iter(self._items))]

    def snapshot(self, conversation_key: str, *, now: float | None = None) -> tuple[Perception, ...]:
        return tuple(item for item, _ in self.active(conversation_key, now=now))

    def active(self, conversation_key: str, *, now: float | None = None
               ) -> tuple[tuple[Perception, float], ...]:
        cutoff = (monotonic() if now is None else now) - self.ttl_seconds
        return tuple((item, seen - cutoff)
                     for (scope, _, _), (seen, item) in reversed(self._items.items())
                     if scope == conversation_key and seen > cutoff)

    def _expire(self, now: float) -> None:
        for key, (seen, _) in tuple(self._items.items()):
            if now - seen >= self.ttl_seconds:
                del self._items[key]
