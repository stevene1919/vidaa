"""Concurrent multi-TV service dispatch helpers for VIDAA Smart TV."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

_LOGGER = logging.getLogger(__name__)

__all__ = ["async_dispatch_to_clients"]


async def async_dispatch_to_clients[T](
    target_clients: list[Any],
    worker: Callable[[Any], Awaitable[T]],
    service_name: str,
) -> tuple[list[T], list[dict[str, str]]]:
    """Execute a service worker across one or more target clients.

    Single-target calls propagate exceptions directly. Multi-target calls run
    concurrently so one offline or powered-off TV does not block other TVs;
    an exception is raised only when every target fails.
    """
    if len(target_clients) == 1:
        return [await worker(target_clients[0])], []

    results = await asyncio.gather(*(worker(client) for client in target_clients), return_exceptions=True)
    succeeded: list[T] = []
    failures: list[tuple[Any, BaseException]] = []

    for client, res in zip(target_clients, results, strict=True):
        if isinstance(res, BaseException):
            failures.append((client, res))
        else:
            succeeded.append(res)

    if not succeeded and failures:
        first_err = failures[0][1]
        if isinstance(first_err, Exception):
            raise first_err
        raise RuntimeError(str(first_err))

    failed_details: list[dict[str, str]] = []
    for client, err in failures:
        ip = str(getattr(client, "ip", "unknown"))
        _LOGGER.warning("[%s] Service '%s' failed on target TV: %s", ip, service_name, err)
        failed_details.append({"ip": ip, "error": str(err)})

    return succeeded, failed_details
