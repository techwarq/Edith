"""Google OAuth: token loading/refresh/caching, and the one-time login flow.

Token is stored as JSON (not pickle) at ~/.edith/google_token.json — human
inspectable, no deserialization risk. get_credentials() never raises for a
missing/invalid token; it returns None so tool functions can degrade to a
clear "run /google login first" string instead of crashing the agent loop.
"""

import base64
import logging
import os
import webbrowser

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from edith.config import GOOGLE_CLIENT_SECRET_PATH, GOOGLE_SCOPES, GOOGLE_TOKEN_PATH

logger = logging.getLogger("edith.integrations.google.auth")


class GoogleAuthError(Exception):
    pass


def write_credentials_from_env() -> None:
    """For the hosted server: /google login's local-browser redirect flow
    doesn't work remotely, so instead of running it there, the already-
    obtained local credential files get base64'd into GOOGLE_CLIENT_SECRET_B64
    / GOOGLE_TOKEN_B64 env vars and written out here on startup. No-op
    locally, where the env vars aren't set and the files already exist from
    a real /google login.

    Writes whenever the env var's decoded content differs from what's on
    the volume (not just when the file is missing) — otherwise a re-login
    done locally after a scope change (e.g. adding Sheets write) would never
    reach the hosted volume, since the old file's mere presence would always
    block the write. Comparing content, not just existence, means a normal
    restart after an in-container token refresh is still a no-op (the file
    differs from the bootstrap env var only in access_token/expiry, which
    get_credentials() will just refresh again on demand — harmless)."""
    for path, env_var in (
        (GOOGLE_CLIENT_SECRET_PATH, "GOOGLE_CLIENT_SECRET_B64"),
        (GOOGLE_TOKEN_PATH, "GOOGLE_TOKEN_B64"),
    ):
        b64 = os.environ.get(env_var, "").strip()
        if not b64:
            continue
        try:
            content = base64.b64decode(b64)
        except Exception:  # noqa: BLE001 — best-effort; get_credentials()/run_login_flow() degrade cleanly if this fails
            logger.exception("Failed to decode %s", env_var)
            continue
        if path.exists() and path.read_bytes() == content:
            continue
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            logger.info("Wrote %s from %s", path, env_var)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to write %s from %s", path, env_var)


def get_credentials() -> Credentials | None:
    if not GOOGLE_TOKEN_PATH.exists():
        return None

    try:
        creds = Credentials.from_authorized_user_file(str(GOOGLE_TOKEN_PATH), GOOGLE_SCOPES)
    except ValueError:
        logger.warning("google_token.json is malformed")
        return None

    if creds.valid:
        return creds

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError:
            logger.warning("Google token refresh failed — re-run /google login")
            return None
        GOOGLE_TOKEN_PATH.write_text(creds.to_json())
        return creds

    return None


def run_login_flow() -> None:
    if not GOOGLE_CLIENT_SECRET_PATH.exists():
        raise GoogleAuthError(
            f"No client secret found at {GOOGLE_CLIENT_SECRET_PATH}. "
            "Create OAuth Desktop credentials in Google Cloud Console and save the "
            "downloaded JSON there first."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(GOOGLE_CLIENT_SECRET_PATH), GOOGLE_SCOPES)
    try:
        creds = flow.run_local_server(port=0)
    except webbrowser.Error as e:
        # This only works on a machine with a real browser — running it against the
        # hosted server (no display, no browser) used to crash the whole SSE stream
        # instead of failing cleanly. /google login has to be run from a local
        # terminal; the resulting token then needs to be bridged to the hosted
        # deployment via GOOGLE_TOKEN_B64 (see write_credentials_from_env's docstring).
        raise GoogleAuthError(
            "Can't open a browser here — /google login only works from a local terminal, "
            "not the hosted server. Run it locally (edith/.venv/bin/edith or `python main.py`), "
            "then the resulting token needs to be re-deployed to the hosted server."
        ) from e
    GOOGLE_TOKEN_PATH.write_text(creds.to_json())
