"""
Async utility functions for executing synchronous code in thread pools.
"""
from __future__ import annotations

import asyncio
from typing import Any, Callable, Optional


async def call_threadsafe(fn: Callable, timeout: Optional[float] = None, **kwargs) -> Any:
    """
    Execute a synchronous function in a thread pool to avoid blocking the event loop.

    Filters out None values from kwargs before passing to the function.

    Args:
        fn: Synchronous function to execute
        timeout: Optional timeout in seconds. Raises asyncio.TimeoutError if exceeded.
        **kwargs: Keyword arguments to pass (None values filtered out)

    Returns:
        Result of the function call
    """
    filtered_kwargs = {k: v for k, v in kwargs.items() if v is not None}
    coro = asyncio.to_thread(fn, **filtered_kwargs)
    if timeout is not None:
        return await asyncio.wait_for(coro, timeout=timeout)
    return await coro
