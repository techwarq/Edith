"""Temporal Cloud client construction — shared by worker.py and the schedule_job tool."""

from temporalio.client import Client

from edith.config import Settings


class TemporalNotConfigured(Exception):
    pass


async def get_client(settings: Settings) -> Client:
    if not (settings.temporal_address and settings.temporal_namespace and settings.temporal_api_key):
        raise TemporalNotConfigured(
            "Temporal Cloud isn't configured — set TEMPORAL_ADDRESS, TEMPORAL_NAMESPACE, "
            "and TEMPORAL_API_KEY in .env."
        )
    # tls defaults to True automatically when api_key is set (temporalio.client.Client.connect).
    return await Client.connect(
        settings.temporal_address,
        namespace=settings.temporal_namespace,
        api_key=settings.temporal_api_key,
    )
