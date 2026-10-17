"""Optional feature packs, switched on with EDITH_PLUGINS (comma-separated names, e.g.
"career"). A plugin is a package exposing tool_modules(), setup(conn),
ensure_schema(conn) and routers(...). Schemas are created for every installed
plugin so data survives toggling one off; tools, setup and HTTP routes load only
for enabled plugins."""

import importlib
import os
import sqlite3
from types import ModuleType

INSTALLED = ("career",)


def enabled_names() -> list[str]:
    raw = os.environ.get("EDITH_PLUGINS", "")
    return [n.strip() for n in raw.split(",") if n.strip() in INSTALLED]


def _load(name: str) -> ModuleType:
    return importlib.import_module(f"edith.plugins.{name}")


def enabled() -> list[ModuleType]:
    return [_load(n) for n in enabled_names()]


def ensure_schemas(conn: sqlite3.Connection) -> None:
    for name in INSTALLED:
        _load(name).ensure_schema(conn)
