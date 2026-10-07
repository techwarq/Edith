import inspect
from typing import Callable, Optional


class ToolRegistry:
    def __init__(self) -> None:
        self._schemas: list[dict] = []
        self._dispatch: dict[str, Callable[..., str]] = {}
        self._wants_progress: set[str] = set()
        self._aliases: dict[str, str] = {}

    def alias(self, old_name: str, new_name: str) -> None:
        self._aliases[old_name] = new_name

    def register(self, schema: dict, fn: Callable[..., str]) -> None:
        self._schemas.append(schema)
        name = schema["function"]["name"]
        self._dispatch[name] = fn
        if "on_progress" in inspect.signature(fn).parameters:
            self._wants_progress.add(name)

    def dispatch(self, name: str, args: dict, on_progress: Optional[Callable[[str], None]] = None) -> str:
        name = self._aliases.get(name, name)
        fn = self._dispatch.get(name)
        if fn is None:
            return f"ERROR: unknown tool '{name}'"
        if on_progress is not None and name in self._wants_progress:
            return fn(**args, on_progress=on_progress)
        return fn(**args)

    def schemas(self) -> list[dict]:
        return list(self._schemas)
