from types import ModuleType
from typing import Callable, Optional

from edith.tools.base import TOOL_ATTR, ToolContext, spec_of


class ToolRegistry:
    def __init__(self, ctx: Optional[ToolContext] = None) -> None:
        self.ctx = ctx or ToolContext()
        self._schemas: list[dict] = []
        self._dispatch: dict[str, Callable[..., str]] = {}
        self._takes_ctx: set[str] = set()
        self._wants_progress: set[str] = set()
        self._aliases: dict[str, str] = {}

    def register(self, *fns: Callable[..., str]) -> None:
        for fn in fns:
            spec = spec_of(fn)
            self._add(spec.schema, fn)
            if spec.takes_ctx:
                self._takes_ctx.add(spec.name)
            if spec.takes_progress:
                self._wants_progress.add(spec.name)
            for alias in spec.aliases:
                self._aliases[alias] = spec.name

    def register_module(self, module: ModuleType) -> None:
        self.register(
            *(
                v
                for v in vars(module).values()
                if hasattr(v, TOOL_ATTR) and getattr(v, "__module__", None) == module.__name__
            )
        )

    def register_schema(self, schema: dict, fn: Callable[..., str]) -> None:
        self._add(schema, fn)

    def _add(self, schema: dict, fn: Callable[..., str]) -> None:
        name = schema["function"]["name"]
        if name in self._dispatch:
            raise ValueError(f"tool name {name!r} is already registered")
        self._schemas.append(schema)
        self._dispatch[name] = fn

    def dispatch(self, name: str, args: dict, on_progress: Optional[Callable[[str], None]] = None) -> str:
        name = self._aliases.get(name, name)
        fn = self._dispatch.get(name)
        if fn is None:
            return f"ERROR: unknown tool '{name}'"
        if on_progress is not None and name in self._wants_progress:
            args = {**args, "on_progress": on_progress}
        if name in self._takes_ctx:
            return fn(self.ctx, **args)
        return fn(**args)

    def schemas(self) -> list[dict]:
        return list(self._schemas)
