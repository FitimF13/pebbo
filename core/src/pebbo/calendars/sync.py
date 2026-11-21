"""Read-only calendar subscriptions (ICS addresses), fetched only from allowed hosts.

The owner enters the address of a calendar feed in the control centre. Pebbo contacts only
the host in that address, and only:

- if the host is on the home network (an IP address in a private range, or a name such as
  ``radicale.local``, ``nas.lan``, ``*.home.arpa`` or a name without a dot), or
- if the owner switched on "Externen Host erlauben" for this source. Then that one host is
  added to the runtime network guard (``pebbo.netguard``) and HTTPS is required.

Redirects to another host are refused by the network guard. Proxies are never used, so the
feed is fetched directly from the host the owner sees in the control centre.
"""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import urllib.request
from collections.abc import Callable
from urllib.parse import urlsplit

from loguru import logger

from pebbo import clock, netguard
from pebbo.calendars.ics import parse_ics
from pebbo.calendars.storage import CalendarBook, CalendarSource, calendar_book
from pebbo.store import Store

Fetch = Callable[[str], str]
MAX_BYTES = 5 * 1024 * 1024
SYNC_INTERVAL_SECONDS = 30 * 60
_LOCAL_SUFFIXES = (".local", ".lan", ".home.arpa", ".internal", ".localdomain")


class CalendarAddressError(ValueError):
    """An address Pebbo will not subscribe to. The message is German."""


def check_address(url: str) -> tuple[str, str, bool]:
    """Clean a feed address. Returns the address, its host and whether the host is external."""
    url = url.strip()
    if url.lower().startswith("webcal://"):
        url = "https://" + url[len("webcal://") :]
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or not host:
        raise CalendarAddressError("Die Adresse muss mit https:// oder webcal:// beginnen.")
    if parts.username or parts.password:
        raise CalendarAddressError("Bitte keine Zugangsdaten in der Adresse.")
    external = not is_home_host(host)
    if external and parts.scheme != "https":
        raise CalendarAddressError("Kalender ausserhalb des Heimnetzes gehen nur über https://.")
    return url, host, external


def is_home_host(host: str) -> bool:
    """Whether a host is on the home network, judged from the address alone without a lookup."""
    host = host.lower().rstrip(".")
    try:
        ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return "." not in host or host.endswith(_LOCAL_SUFFIXES)
    return netguard.is_local_address(host)


def fetch_url(url: str) -> str:
    """Download a feed without any proxy, at most :data:`MAX_BYTES`."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(url, headers={"User-Agent": "Pebbo", "Accept": "text/calendar"})  # noqa: S310
    with opener.open(request, timeout=20) as response:
        data: bytes = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("Der Kalender ist zu gross.")
    return data.decode("utf-8", errors="replace")


def allowed_hosts(book: CalendarBook) -> set[str]:
    return {s.host for s in book.sources() if s.external and s.allow_external}


def apply_guard(book: CalendarBook, previous: set[str] | None = None) -> set[str]:
    """Allow exactly the external hosts the owner allowed. Returns them."""
    hosts = allowed_hosts(book)
    netguard.allow(hosts)
    stale = (previous or set()) - hosts
    if stale:
        netguard.revoke(stale)
    return hosts


def sync_source(store: Store, source: CalendarSource, fetch: Fetch = fetch_url) -> int:
    """Read a subscription again. Returns the number of events, raises on failure."""
    book = calendar_book(store)
    if source.external and not source.allow_external:
        raise PermissionError("Externer Host nicht freigegeben.")
    if source.external:
        netguard.allow((source.host,))
    try:
        events = parse_ics(fetch(source.url), clock.timezone())
    except Exception as error:
        message = str(error) or type(error).__name__
        book.synced(source.id, message[:200])
        raise
    count = book.replace_source_events(source.id, source.person_id, events)
    book.synced(source.id, None)
    logger.info("Calendar source {} synced with {} events", source.id, count)
    return count


class CalendarSync:
    """Re-reads every allowed subscription every 30 minutes."""

    def __init__(
        self, store: Store, fetch: Fetch = fetch_url, interval: float = SYNC_INTERVAL_SECONDS
    ) -> None:
        self._store = store
        self._fetch = fetch
        self._interval = interval
        self._task: asyncio.Task[None] | None = None
        self._hosts: set[str] = set()

    def refresh_guard(self) -> None:
        self._hosts = apply_guard(calendar_book(self._store), self._hosts)

    async def sync(self, source_id: int) -> int:
        source = calendar_book(self._store).source(source_id)
        if source is None:
            raise KeyError(source_id)
        self.refresh_guard()
        return await asyncio.to_thread(sync_source, self._store, source, self._fetch)

    async def sync_all(self) -> None:
        self.refresh_guard()
        for source in calendar_book(self._store).sources():
            if source.external and not source.allow_external:
                continue
            try:
                await asyncio.to_thread(sync_source, self._store, source, self._fetch)
            except Exception as error:
                logger.warning("Calendar source {} could not be synced: {}", source.id, type(error).__name__)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        while True:
            await self.sync_all()
            await asyncio.sleep(self._interval)
