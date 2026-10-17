import inspect
import re
import sqlite3
import types
import typing
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Literal, Optional, Union

if TYPE_CHECKING:
    from qdrant_client import QdrantClient

    from edith.config import Settings
    from edith.memory.brain import Brain

TOOL_ATTR = "__edith_tool__"
_RESERVED_PARAMS = ("ctx", "on_progress")


@dataclass
class ToolContext:
    conn: Optional[sqlite3.Connection] = None
    settings: Optional["Settings"] = None
    genai_client: Any = None
    llm_client: Any = None
    genai_model: str = ""
    qdrant_client: Optional["QdrantClient"] = None
    brain: Optional["Brain"] = None


@dataclass(frozen=True)
class ToolSpec:
    name: str
    schema: dict
    takes_ctx: bool
    takes_progress: bool
    aliases: tuple[str, ...]


def tool(fn: Optional[Callable[..., str]] = None, *, name: str = "", aliases: tuple[str, ...] = ()):
    def wrap(f: Callable[..., str]) -> Callable[..., str]:
        setattr(f, TOOL_ATTR, _build_spec(f, name or f.__name__, tuple(aliases)))
        return f

    return wrap(fn) if fn is not None else wrap


def spec_of(fn: Callable[..., str]) -> ToolSpec:
    spec = getattr(fn, TOOL_ATTR, None)
    if spec is None:
        raise TypeError(f"{getattr(fn, '__qualname__', fn)!r} isn't decorated with @tool")
    return spec


def _build_spec(fn: Callable[..., str], name: str, aliases: tuple[str, ...]) -> ToolSpec:
    description, arg_docs = _parse_docstring(inspect.getdoc(fn) or "")
    if not description:
        raise TypeError(f"tool {name!r} needs a docstring — it's the description the model reads")

    sig = inspect.signature(fn)
    hints = typing.get_type_hints(fn)
    params = list(sig.parameters.values())
    takes_ctx = bool(params) and params[0].name == "ctx"

    properties: dict[str, dict] = {}
    required: list[str] = []
    for p in params:
        if p.name in _RESERVED_PARAMS:
            continue
        if p.name not in hints:
            raise TypeError(f"tool {name!r}: parameter {p.name!r} needs a type hint")
        prop = _json_schema(hints[p.name], f"{name}.{p.name}")
        if p.name in arg_docs:
            prop["description"] = arg_docs[p.name]
        properties[p.name] = prop
        if p.default is inspect.Parameter.empty:
            required.append(p.name)

    unknown = set(arg_docs) - set(properties)
    if unknown:
        raise TypeError(f"tool {name!r}: Args documents unknown parameter(s) {sorted(unknown)}")

    parameters: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        parameters["required"] = required
    schema = {"type": "function", "function": {"name": name, "description": description, "parameters": parameters}}
    return ToolSpec(name, schema, takes_ctx, "on_progress" in sig.parameters, aliases)


_SCALARS = {str: "string", int: "integer", float: "number", bool: "boolean"}


def _json_schema(hint: Any, where: str) -> dict:
    origin = typing.get_origin(hint)
    args = typing.get_args(hint)

    if origin in (Union, types.UnionType):
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) != 1:
            raise TypeError(f"{where}: only Optional[X] unions are supported, got {hint}")
        return _json_schema(non_none[0], where)
    if hint in _SCALARS:
        return {"type": _SCALARS[hint]}
    if origin is Literal:
        kinds = {type(a) for a in args}
        if len(kinds) != 1 or next(iter(kinds)) not in _SCALARS:
            raise TypeError(f"{where}: Literal values must all share one scalar type, got {hint}")
        return {"type": _SCALARS[next(iter(kinds))], "enum": list(args)}
    if origin is list:
        if not args:
            raise TypeError(f"{where}: give list an item type, e.g. list[str]")
        return {"type": "array", "items": _json_schema(args[0], where)}
    if origin is dict:
        if not args or args[0] is not str:
            raise TypeError(f"{where}: dict must be dict[str, X]")
        return {"type": "object", "additionalProperties": _json_schema(args[1], where)}
    raise TypeError(f"{where}: unsupported type {hint}")


_ARG_LINE = re.compile(r"(\w+):\s*(.*)")


def _parse_docstring(doc: str) -> tuple[str, dict[str, str]]:
    lines = doc.splitlines()
    split = next((i for i, line in enumerate(lines) if line.strip() == "Args:"), len(lines))
    return _join_paragraphs(lines[:split]), _parse_args(lines[split + 1 :])


def _join_paragraphs(lines: list[str]) -> str:
    paragraphs, current = [], []
    for line in lines:
        if line.strip():
            current.append(line.strip())
        elif current:
            paragraphs.append(" ".join(current))
            current = []
    if current:
        paragraphs.append(" ".join(current))
    return "\n\n".join(paragraphs)


def _parse_args(lines: list[str]) -> dict[str, str]:
    docs: dict[str, list[str]] = {}
    entry_indent = None
    current = None
    for line in lines:
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        if entry_indent is None:
            entry_indent = indent
        match = _ARG_LINE.fullmatch(line.strip())
        if indent == entry_indent and match:
            current = match.group(1)
            docs[current] = [match.group(2)]
        elif current is not None and indent > entry_indent:
            docs[current].append(line.strip())
        else:
            raise TypeError(f"can't parse Args line: {line!r}")
    return {k: " ".join(p for p in v if p) for k, v in docs.items()}
