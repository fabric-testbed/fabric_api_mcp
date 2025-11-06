#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Callable

# Collection types
Sites = List[Dict[str, Any]]
Hosts = List[Dict[str, Any]]
FacilityPorts = List[Dict[str, Any]]
Links = List[Dict[str, Any]]

@dataclass
class CacheSnapshot:
    """Immutable-ish snapshot of cached resources."""
    ts: float
    sites: Sites = field(default_factory=list)
    hosts: Hosts = field(default_factory=list)
    facility_ports: FacilityPorts = field(default_factory=list)
    links: Links = field(default_factory=list)

class ResourceCache:
    """
    Async cache that periodically refreshes FABRIC advertised resources.
    - Token-independent: uses the latest seen token if available, otherwise public endpoints via id_token=None
    - Thread/async safe: readers are lock-free; writers use a single async lock
    - Designed to back MCP query-* tools with fast, in-memory lists
    """

    def __init__(self, interval_seconds: int = 300, max_fetch: int = 5000) -> None:
        self._interval = max(30, int(interval_seconds))
        self._max_fetch = max(100, int(max_fetch))

        self._snap: CacheSnapshot = CacheSnapshot(ts=0.0)
        self._rw_lock = asyncio.Lock()      # protect writer updates to _snap
        self._token_lock = asyncio.Lock()   # protect _last_good_token
        self._last_good_token: Optional[str] = None

        self._refresh_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

        # fm_factory returns ONLY a FabricManagerV2 (token handled internally by cache)
        self._fm_factory: Optional[Callable[[], Any]] = None
        self.log = logging.getLogger("fabric.mcp")

    # ----------------------------
    # Lifecycle
    # ----------------------------
    def wire_fm_factory(self, fm_factory: Callable[[], Any]) -> None:
        """Provide FabricManagerV2 factory (no token argument)."""
        self._fm_factory = fm_factory

    async def start(self) -> None:
        if self._refresh_task is None:
            self._stop_event.clear()
            self._refresh_task = asyncio.create_task(self._periodic_refresh_loop())

    async def stop(self) -> None:
        if self._refresh_task:
            self._stop_event.set()
            try:
                await asyncio.wait_for(self._refresh_task, timeout=5)
            except asyncio.TimeoutError:
                self._refresh_task.cancel()
            self._refresh_task = None

    # ----------------------------
    # Token tracking (optional)
    # ----------------------------
    async def note_token(self, token: Optional[str]) -> None:
        """Record latest good user token (if any)."""
        if not token:
            return
        async with self._token_lock:
            self._last_good_token = token

    async def _get_refresh_token(self) -> Optional[str]:
        async with self._token_lock:
            return self._last_good_token

    # ----------------------------
    # Readers
    # ----------------------------
    def snapshot(self) -> CacheSnapshot:
        # Read is lock-free: assignment of a new CacheSnapshot is atomic at ref level.
        return self._snap

    def has_data(self) -> bool:
        s = self._snap
        return bool(s.sites or s.hosts or s.facility_ports or s.links)

    # ----------------------------
    # Background refresh
    # ----------------------------
    async def _periodic_refresh_loop(self) -> None:
        while not self._fm_factory:
            if self._stop_event.is_set():
                return
            await asyncio.sleep(0.2)

        # Initial, non-fatal attempt
        try:
            await self.refresh_once()
        except Exception:
            pass

        while not self._stop_event.is_set():
            try:
                await self.refresh_once()
            except Exception:
                # swallow; next tick will retry
                pass
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval)
            except asyncio.TimeoutError:
                pass

    async def refresh_once(self) -> None:
        """
        Pull all advertised data, using last_good_token if set; else id_token=None (public).
        Uses FabricManagerV2.query_* which you wired to switch to public resources when token is None.
        """
        if not self._fm_factory:
            return
        fm = self._fm_factory()
        token = await self._get_refresh_token()  # may be None

        async def _page(fetch_fn, **kwargs) -> List[Dict[str, Any]]:
            out: List[Dict[str, Any]] = []
            offset = 0
            limit = min(self._max_fetch, int(kwargs.pop("limit", 500)))
            while True:
                self.log.debug("Fetching %d of %d", offset, limit)
                page = await asyncio.to_thread(
                    fetch_fn,
                    id_token=token,   # <-- None triggers public path in your TopologyQueryAPI
                    limit=limit,
                    offset=offset,
                    **kwargs
                )
                if not page:
                    break
                out.extend(page)
                if len(page) < limit:
                    break
                offset += limit
            return out

        sites = await _page(fm.query_sites, filters=None)
        hosts = await _page(fm.query_hosts, filters=None)
        facility_ports = await _page(fm.query_facility_ports, filters=None)
        links = await _page(fm.query_links, filters=None)

        snap = CacheSnapshot(
            ts=time.time(),
            sites=sites,
            hosts=hosts,
            facility_ports=facility_ports,
            links=links,
        )
        async with self._rw_lock:
            self._snap = snap
