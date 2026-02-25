"""
Async utility functions for executing synchronous code in thread pools.
"""
from __future__ import annotations

import asyncio
from typing import Any, Callable


async def call_threadsafe(fn: Callable, **kwargs) -> Any:
    """
    Execute a synchronous function in a thread pool to avoid blocking the event loop.

    Filters out None values from kwargs before passing to the function.

    Args:
        fn: Synchronous function to execute
        **kwargs: Keyword arguments to pass (None values filtered out)

    Returns:
        Result of the function call
    """
    filtered_kwargs = {k: v for k, v in kwargs.items() if v is not None}
    return await asyncio.to_thread(fn, **filtered_kwargs)
