"""Tool schema definitions + dispatch table.

Tool functions must be pure text in/out — no print()/input() — so the
agent-core I/O contract holds. Instances are built per-session (bound to a
db connection / llm client via closures) rather than held as module globals.
"""

import inspect
from typing import Callable, Optional


class ToolRegistry:
    def __init__(self) -> None:
        self._schemas: list[dict] = []
        self._dispatch: dict[str, Callable[..., str]] = {}
        # Tools that declare an on_progress parameter opt into receiving the
        # live-status callback (see llm/client.py's on_progress) — most tools
        # don't want it, so it's only passed to ones that asked for it by
        # name, rather than changing every tool function's signature.
        self._wants_progress: set[str] = set()

    def register(self, schema: dict, fn: Callable[..., str]) -> None:
        self._schemas.append(schema)
        name = schema["function"]["name"]
        self._dispatch[name] = fn
        if "on_progress" in inspect.signature(fn).parameters:
            self._wants_progress.add(name)

    def dispatch(self, name: str, args: dict, on_progress: Optional[Callable[[str], None]] = None) -> str:
        fn = self._dispatch.get(name)
        if fn is None:
            return f"ERROR: unknown tool '{name}'"
        if on_progress is not None and name in self._wants_progress:
            return fn(**args, on_progress=on_progress)
        return fn(**args)

    def schemas(self) -> list[dict]:
        return list(self._schemas)
