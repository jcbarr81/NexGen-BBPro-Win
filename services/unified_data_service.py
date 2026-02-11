from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Dict, Iterable, Optional, Tuple, TypeVar

from utils import path_utils
from utils.safe_copy import deepcopy

_LOGGER = logging.getLogger(__name__)

EventPayload = Dict[str, Any]
EventCallback = Callable[[EventPayload], None]
T = TypeVar("T")


class EventBus:
    """Lightweight pub/sub bus so UI components can observe data mutations."""

    def __init__(self) -> None:
        self._subscribers: Dict[str, list[EventCallback]] = defaultdict(list)
        self._lock = RLock()

    def subscribe(self, topic: str, callback: EventCallback) -> Callable[[], None]:
        """Register *callback* for *topic*; returns an unsubscribe closure."""

        with self._lock:
            self._subscribers[topic].append(callback)

        def _unsubscribe() -> None:
            self.unsubscribe(topic, callback)

        return _unsubscribe

    def unsubscribe(self, topic: str, callback: EventCallback) -> None:
        """Remove *callback* from *topic* if previously subscribed."""

        with self._lock:
            callbacks = self._subscribers.get(topic)
            if not callbacks:
                return
            try:
                callbacks.remove(callback)
            except ValueError:
                return
            if not callbacks:
                self._subscribers.pop(topic, None)

    def publish(self, topic: str, payload: Optional[EventPayload] = None) -> None:
        """Emit *payload* to every subscriber registered for *topic*."""

        payload = payload or {}
        with self._lock:
            callbacks = list(self._subscribers.get(topic, ()))
        for callback in callbacks:
            try:
                callback(payload)
            except Exception:  # pragma: no cover - defensive logging
                _LOGGER.exception("UnifiedDataService subscriber failed for %s", topic)


class UnifiedDataService:
    """Repository facade that caches common CSV/JSON-backed resources."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._player_cache: Dict[Path, Iterable[Any]] = {}
        self._roster_cache: Dict[Tuple[str, Path], Any] = {}
        self._document_cache: Dict[Path, Any] = {}
        self.events = EventBus()

    # -- Shared helpers -----------------------------------------------------

    def _resolve_path(self, path: Path | str) -> Path:
        candidate = path_utils.resolve_app_path(path)
        return candidate.resolve(strict=False)

    # -- Player access ------------------------------------------------------

    def get_players(self, file_path: Path | str, loader: Callable[[Path], Iterable[T]]) -> list[T]:
        """Return players loaded from *file_path*, caching via *loader*."""

        resolved = self._resolve_path(file_path)
        with self._lock:
            cached = self._player_cache.get(resolved)
        if cached is None:
            players = tuple(loader(resolved))
            with self._lock:
                self._player_cache[resolved] = players
            self.events.publish("players.loaded", {"path": resolved})
            cached_iterable = players
        else:
            cached_iterable = cached
        return list(cached_iterable)

    def invalidate_players(self, file_path: Path | str | None = None) -> None:
        """Clear cached players for *file_path* (or all players when omitted)."""

        if file_path is None:
            with self._lock:
                paths = list(self._player_cache.keys())
                self._player_cache.clear()
            for path in paths:
                self.events.publish("players.invalidated", {"path": path})
            return

        resolved = self._resolve_path(file_path)
        with self._lock:
            existed = self._player_cache.pop(resolved, None) is not None
        if existed:
            self.events.publish("players.invalidated", {"path": resolved})

    def update_players(self, file_path: Path | str, players: Iterable[T]) -> None:
        """Replace cached players for *file_path* and broadcast update."""

        resolved = self._resolve_path(file_path)
        payload = tuple(players)
        with self._lock:
            self._player_cache[resolved] = payload
        self.events.publish("players.updated", {"path": resolved})

    # -- Roster access ------------------------------------------------------

    def get_roster(
        self,
        team_id: str,
        roster_dir: Path | str,
        loader: Callable[[str, Path], T],
    ) -> T:
        """Return *team_id* roster rooted at *roster_dir* via *loader*."""

        resolved_dir = self._resolve_path(roster_dir)
        key = (team_id, resolved_dir)
        with self._lock:
            roster = self._roster_cache.get(key)
        if roster is None:
            roster = loader(team_id, resolved_dir)
            with self._lock:
                self._roster_cache[key] = roster
            self.events.publish(
                "rosters.loaded",
                {"team_id": team_id, "path": resolved_dir},
            )
        return roster

    def update_roster(self, team_id: str, roster_dir: Path | str, roster: T) -> None:
        """Refresh cache entry for *team_id* and mark subscribers notified."""

        resolved_dir = self._resolve_path(roster_dir)
        key = (team_id, resolved_dir)
        with self._lock:
            self._roster_cache[key] = roster
        self.events.publish(
            "rosters.updated",
            {"team_id": team_id, "path": resolved_dir},
        )

    def invalidate_roster(self, team_id: Optional[str] = None, roster_dir: Path | str | None = None) -> None:
        """Invalidate cached rosters matching *team_id* and/or *roster_dir*."""

        resolved_dir = self._resolve_path(roster_dir) if roster_dir is not None else None
        with self._lock:
            if team_id is None and resolved_dir is None:
                keys = list(self._roster_cache.keys())
                self._roster_cache.clear()
            else:
                keys = [
                    key
                    for key in list(self._roster_cache)
                    if (team_id is None or key[0] == team_id)
                    and (resolved_dir is None or key[1] == resolved_dir)
                ]
                for key in keys:
                    self._roster_cache.pop(key, None)
        for tid, path in keys:
            self.events.publish("rosters.invalidated", {"team_id": tid, "path": path})

    # -- Generic document access ----------------------------------------------

    def get_document(
        self,
        file_path: Path | str,
        loader: Callable[[Path], T],
        *,
        topic: str,
    ) -> T:
        """Return cached document located at *file_path* loaded via *loader*."""

        resolved = self._resolve_path(file_path)
        with self._lock:
            cached = self._document_cache.get(resolved)
        if cached is None:
            document = loader(resolved)
            with self._lock:
                self._document_cache[resolved] = document
            self.events.publish(f"{topic}.loaded", {"path": resolved})
            payload = document
        else:
            payload = cached
        return deepcopy(payload)

    def update_document(
        self,
        file_path: Path | str,
        document: T,
        *,
        topic: str,
    ) -> None:
        """Update cached document, emitting an event for subscribers."""

        resolved = self._resolve_path(file_path)
        snapshot = deepcopy(document)
        with self._lock:
            self._document_cache[resolved] = snapshot
        self.events.publish(f"{topic}.updated", {"path": resolved})

    def invalidate_document(
        self,
        file_path: Path | str | None = None,
        *,
        topic: str | None = None,
    ) -> None:
        """Invalidate cached document(s) for *file_path*."""

        if file_path is None:
            with self._lock:
                paths = list(self._document_cache.keys())
                self._document_cache.clear()
            for path in paths:
                self.events.publish(f"{topic or 'document'}.invalidated", {"path": path})
            return

        resolved = self._resolve_path(file_path)
        with self._lock:
            existed = self._document_cache.pop(resolved, None) is not None
        if existed:
            self.events.publish(f"{topic or 'document'}.invalidated", {"path": resolved})


_SERVICE: UnifiedDataService | None = None


def get_unified_data_service() -> UnifiedDataService:
    """Return the process-wide singleton service instance."""

    global _SERVICE
    if _SERVICE is None:
        _SERVICE = UnifiedDataService()
    return _SERVICE


__all__ = [
    "EventBus",
    "UnifiedDataService",
    "get_unified_data_service",
]
