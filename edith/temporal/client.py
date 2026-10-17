"""Temporal client construction — shared by worker.py and the schedule_job tool.

Works with Temporal Cloud (address + namespace + API key, TLS) or a self-hosted /
local dev server (address only, `docker compose --profile scheduler up`)."""

from temporalio.client import Client

from edith.config import Settings


class TemporalNotConfigured(Exception):
    pass


async def get_client(settings: Settings) -> Client:
    if not settings.temporal_address:
        raise TemporalNotConfigured(
            "Scheduling isn't set up — run `docker compose --profile scheduler up`, or set "
            "TEMPORAL_ADDRESS (plus TEMPORAL_NAMESPACE and TEMPORAL_API_KEY for Temporal Cloud) in .env."
        )
    # tls defaults to True automatically when api_key is set (temporalio.client.Client.connect).
    return await Client.connect(
        settings.temporal_address,
        namespace=settings.temporal_namespace or "default",
        api_key=settings.temporal_api_key or None,
    )
