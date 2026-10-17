"""The career plugin's profile — everything personal its tools write with: who you
are, what you've built, how your cold emails read, what jobs you want, and the
voice of your content planner. Lives outside the repo at EDITH_CAREER_PROFILE
(default ~/.edith/career_profile.json); see career_profile.example.json."""

import json
import os
from pathlib import Path
from typing import Any

from edith.config import EDITH_HOME

EXAMPLE_PATH = Path(__file__).with_name("career_profile.example.json")

_cache: dict[str, Any] = {"mtime": None, "data": None}


class ProfileMissing(RuntimeError):
    pass


def path() -> Path:
    return Path(os.environ.get("EDITH_CAREER_PROFILE", EDITH_HOME / "career_profile.json"))


def load() -> dict[str, Any]:
    """The profile, or {} if the file doesn't exist. Re-read when the file changes."""
    p = path()
    if not p.exists():
        return {}
    mtime = p.stat().st_mtime
    if _cache["mtime"] != mtime:
        _cache["data"], _cache["mtime"] = json.loads(p.read_text()), mtime
    return _cache["data"]


def require() -> dict[str, Any]:
    data = load()
    if not data:
        raise ProfileMissing(
            f"The career plugin needs your profile: copy {EXAMPLE_PATH.name} (in edith/plugins/career/) "
            f"to {path()} and fill it in."
        )
    return data


def section(name: str) -> dict[str, Any]:
    return require().get(name) or {}
