from typing import Callable, Literal, Optional

import pytest

from edith.tools.base import ToolContext, spec_of, tool
from edith.tools.registry import ToolRegistry


@tool
def _sample(
    ctx: ToolContext,
    name: str,
    count: int = 3,
    ratio: float = 0.5,
    loud: bool = False,
    tags: Optional[list[str]] = None,
    fields: dict[str, str] | None = None,
    mode: Literal["a", "b"] = "a",
    on_progress: Optional[Callable[[str], None]] = None,
) -> str:
    """First line of the description,
    continued on the next line.

    Second paragraph.

    Args:
        name: Who to greet
        tags: Labels to attach,
            wrapped onto a second line
    """
    return f"{ctx.genai_model}:{name}:{count}"


def test_schema_built_from_signature_and_docstring():
    schema = spec_of(_sample).schema

    fn = schema["function"]
    assert fn["name"] == "_sample"
    assert fn["description"] == "First line of the description, continued on the next line.\n\nSecond paragraph."
    assert fn["parameters"] == {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Who to greet"},
            "count": {"type": "integer"},
            "ratio": {"type": "number"},
            "loud": {"type": "boolean"},
            "tags": {"type": "array", "items": {"type": "string"}, "description": "Labels to attach, wrapped onto a second line"},
            "fields": {"type": "object", "additionalProperties": {"type": "string"}},
            "mode": {"type": "string", "enum": ["a", "b"]},
        },
        "required": ["name"],
    }


def test_no_required_key_when_everything_has_defaults():
    @tool
    def _all_optional(topic: str = "") -> str:
        """Do it."""
        return topic

    assert "required" not in spec_of(_all_optional).schema["function"]["parameters"]


def test_name_override():
    @tool(name="renamed")
    def _f() -> str:
        """Do it."""
        return ""

    assert spec_of(_f).schema["function"]["name"] == "renamed"


def test_missing_docstring_rejected():
    with pytest.raises(TypeError, match="docstring"):

        @tool
        def _f() -> str:
            return ""


def test_missing_type_hint_rejected():
    with pytest.raises(TypeError, match="type hint"):

        @tool
        def _f(x) -> str:
            """Do it."""
            return ""


def test_args_for_unknown_param_rejected():
    with pytest.raises(TypeError, match="unknown"):

        @tool
        def _f(x: str) -> str:
            """Do it.

            Args:
                y: not a real parameter
            """
            return x


def test_unsupported_type_rejected():
    with pytest.raises(TypeError, match="unsupported"):

        @tool
        def _f(x: set) -> str:
            """Do it."""
            return ""


def test_dispatch_passes_ctx_and_progress():
    seen = []

    @tool
    def _f(ctx: ToolContext, x: str, on_progress: Optional[Callable[[str], None]] = None) -> str:
        """Do it."""
        on_progress("working")
        return f"{ctx.genai_model}:{x}"

    r = ToolRegistry(ToolContext(genai_model="m"))
    r.register(_f)

    assert r.dispatch("_f", {"x": "hi"}, on_progress=seen.append) == "m:hi"
    assert seen == ["working"]


def test_dispatch_without_ctx_param():
    @tool
    def _f(x: str) -> str:
        """Do it."""
        return x

    r = ToolRegistry()
    r.register(_f)

    assert r.dispatch("_f", {"x": "hi"}) == "hi"


def test_aliases_dispatch_to_the_real_tool():
    @tool(aliases=("old_name",))
    def _f() -> str:
        """Do it."""
        return "ok"

    r = ToolRegistry()
    r.register(_f)

    assert r.dispatch("old_name", {}) == "ok"
    assert [s["function"]["name"] for s in r.schemas()] == ["_f"]


def test_duplicate_tool_name_rejected():
    @tool(name="same")
    def _a() -> str:
        """A."""
        return ""

    @tool(name="same")
    def _b() -> str:
        """B."""
        return ""

    r = ToolRegistry()
    r.register(_a)
    with pytest.raises(ValueError, match="already registered"):
        r.register(_b)


def test_register_requires_decorated_function():
    def _plain() -> str:
        return ""

    with pytest.raises(TypeError, match="@tool"):
        ToolRegistry().register(_plain)


def test_register_module_skips_imported_tools():
    import types

    module = types.ModuleType("fake_tools")

    @tool
    def own() -> str:
        """Own tool."""
        return ""

    own.__module__ = "fake_tools"
    module.own = own
    module.imported = _sample

    r = ToolRegistry()
    r.register_module(module)

    assert [s["function"]["name"] for s in r.schemas()] == ["own"]


def test_register_schema_for_externally_defined_tools():
    r = ToolRegistry()
    r.register_schema({"type": "function", "function": {"name": "ext", "parameters": {}}}, lambda **kw: "ext ok")

    assert r.dispatch("ext", {}) == "ext ok"


def test_unknown_tool():
    assert ToolRegistry().dispatch("nope", {}) == "ERROR: unknown tool 'nope'"
