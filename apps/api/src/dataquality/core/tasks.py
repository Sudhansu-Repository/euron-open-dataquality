"""Periodic background tasks, registered by the domains that own them.

The background worker runs every registered task on each tick. Tasks must be idempotent
and safe across replicas (claim rows with ``FOR UPDATE SKIP LOCKED`` or use plain
conditional UPDATEs), because several workers may run them at once.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dataquality.core.container import Container

# Returns how many items it handled: non-zero makes the worker tick again at once.
Task = Callable[["Container"], Awaitable[int]]

_TASKS: dict[str, Task] = {}


def periodic(name: str) -> Callable[[Task], Task]:
    def register(fn: Task) -> Task:
        _TASKS[name] = fn
        return fn

    return register


def tasks() -> dict[str, Task]:
    return dict(_TASKS)
