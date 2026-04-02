"""Helpers for opening player profile dialog variants."""

from __future__ import annotations

from typing import Any

from .window_utils import show_on_top


def _normalize_variant(variant: str | None, use_v2: bool | None) -> str:
    """Return the resolved dialog variant.

    ``use_v2`` wins when explicitly provided. Otherwise, the launcher now
    defaults to V2 and only the explicit legacy token selects the old dialog.
    """

    if use_v2 is True:
        return "v2"
    if use_v2 is False:
        return "legacy"
    normalized = str(variant or "v2").strip().lower()
    if normalized == "legacy":
        return "legacy"
    return "v2"


def create_player_profile_dialog(
    player: Any,
    parent: Any = None,
    *,
    variant: str = "v2",
    use_v2: bool | None = None,
):
    """Create the requested player profile dialog."""

    normalized = _normalize_variant(variant, use_v2)

    if normalized == "v2":
        from .player_profile_dialog_v2 import PlayerProfileDialogV2

        return PlayerProfileDialogV2(player, parent)

    from .player_profile_dialog import PlayerProfileDialog

    return PlayerProfileDialog(player, parent)


def open_player_profile_dialog(
    player: Any,
    parent: Any = None,
    *,
    variant: str = "v2",
    use_v2: bool | None = None,
):
    """Open the requested player profile dialog using the shared window helper."""

    dialog = create_player_profile_dialog(
        player,
        parent,
        variant=variant,
        use_v2=use_v2,
    )
    return show_on_top(dialog)


__all__ = [
    "create_player_profile_dialog",
    "open_player_profile_dialog",
]
