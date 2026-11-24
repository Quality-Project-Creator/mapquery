"""The concurrent engine.

Every provider is called in its own thread. One provider failing never
stops the others, and the results always come back in the input order.
"""

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, Optional

import requests

from .http import RateLimitError
from .models import Channel, ProviderError, ProviderResult, ProviderStatus

# A named job. The name is the provider name.
TaskMap = Dict[str, Callable[[], Any]]

# The channel of every provider, by name.
ChannelMap = Dict[str, Channel]


def status_for_error(exc: BaseException) -> ProviderStatus:
    """Return the status that matches an exception."""
    if isinstance(exc, (requests.Timeout, TimeoutError)):
        return ProviderStatus.TIMEOUT
    if isinstance(exc, RateLimitError):
        return ProviderStatus.RATE_LIMITED
    if isinstance(exc, ProviderError):
        return exc.status
    return ProviderStatus.ERROR


def _run_one(
    name: str,
    task: Callable[[], Any],
    channel: Channel = Channel.DIRECT,
) -> ProviderResult:
    """Run one task and turn the outcome into a ProviderResult.

    The channel is the one that the provider really uses. A failure keeps
    it too, so the status line never says "direct" for a provider that
    answered on its official channel.
    """
    started = time.monotonic()
    try:
        value = task()
    except Exception as exc:  # one failure must not stop the other providers
        elapsed_ms = int((time.monotonic() - started) * 1000)
        message = str(exc) or type(exc).__name__
        return ProviderResult(
            provider=name,
            status=status_for_error(exc),
            channel=channel,
            data=None,
            error=message,
            elapsed_ms=elapsed_ms,
            attempts=1,
        )

    elapsed_ms = int((time.monotonic() - started) * 1000)

    if isinstance(value, ProviderResult):
        if not value.provider:
            value.provider = name
        if not value.elapsed_ms:
            value.elapsed_ms = elapsed_ms
        if not value.attempts and value.status == ProviderStatus.OK:
            # A result that holds an answer made a request. A result that
            # holds a failure, such as a provider that cannot do the
            # feature, made none, so it keeps zero attempts.
            value.attempts = 1
        # The channel map knows which channel the provider really uses, so
        # the result never keeps the default one.
        value.channel = channel
        return value

    return ProviderResult(
        provider=name,
        status=ProviderStatus.OK,
        channel=channel,
        data=value,
        elapsed_ms=elapsed_ms,
        attempts=1,
    )


def run_many(
    tasks: TaskMap,
    jobs: int = 8,
    channels: Optional[ChannelMap] = None,
) -> Dict[str, ProviderResult]:
    """Run every task in a thread pool.

    The returned dict keeps the order of the input dict, never the order
    in which the tasks finished. The channels tell which channel every
    provider uses, so a result carries the channel that was really used.
    """
    results: Dict[str, ProviderResult] = {}
    if not tasks:
        return results

    names = list(tasks.keys())
    workers = max(1, min(int(jobs), len(names)))
    channel_map: ChannelMap = channels or {}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            name: pool.submit(
                _run_one, name, tasks[name], channel_map.get(name, Channel.DIRECT)
            )
            for name in names
        }
        for name in names:
            future = futures[name]
            try:
                results[name] = future.result()
            except Exception as exc:  # safety net, _run_one already catches errors
                results[name] = ProviderResult(
                    provider=name,
                    status=status_for_error(exc),
                    channel=channel_map.get(name, Channel.DIRECT),
                    error=str(exc) or type(exc).__name__,
                )

    return results
