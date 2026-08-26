"""HTTP-facing services. Domain logic stays in `analyst_copilot.collections` and `.services`."""

from analyst_copilot.api.services.collections import CollectionApiService

__all__ = ["CollectionApiService"]
