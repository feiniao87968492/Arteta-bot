from typing import Callable, Optional

import httpx


_shared_async_client = None
_shared_async_client_factory: Optional[Callable[[], object]] = None


def set_shared_async_client_factory(factory: Optional[Callable[[], object]]) -> None:
    global _shared_async_client_factory, _shared_async_client
    _shared_async_client_factory = factory
    _shared_async_client = None


def get_shared_async_client():
    global _shared_async_client
    if _shared_async_client is None:
        factory = _shared_async_client_factory
        if factory is None:
            factory = lambda: httpx.AsyncClient()
        _shared_async_client = factory()
    return _shared_async_client


async def close_shared_async_client() -> None:
    global _shared_async_client
    client = _shared_async_client
    _shared_async_client = None
    if client is not None and hasattr(client, "aclose"):
        await client.aclose()
