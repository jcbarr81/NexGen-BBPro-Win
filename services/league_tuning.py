"""The tuning a league's games are played with, assembled in one order.

1. the engine defaults (``physics_sim.config.DEFAULT_TUNING``),
2. the profile of the league season's engine generation
   (``physics_sim.engine_generation``; nothing for a legacy season),
3. the league's stored commissioner overrides
   (``services.physics_tuning_settings``),
4. the league's rating centres (``services.league_rating_centers``).

:func:`league_tuning_overrides` is layers 2 and 3 -- the part every path
used to get from ``get_physics_tuning_overrides()`` alone -- and
:func:`league_tuning` all four as a ``TuningConfig``. For a legacy season
layer 2 is empty, so the result is exactly the stored overrides, as before
engine generations existed.

Readers: ``playbalance.game_runner`` (season games, and through it the
parallel-day workers, the playoffs and the exhibition), the watch-a-game
socket, the fatigue replay in ``playbalance.usage_store``, the lineup
auto-fill (``utils.lineup_autofill.platoon_tuning``) and the tuning API.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

from physics_sim.engine_generation import engine_profile, normalize_engine_generation
from services.league_rating_centers import (
    get_league_engine_generation,
    league_engine_generation,
    league_rating_centers,
)
from services import physics_tuning_settings

__all__ = ["league_tuning", "league_tuning_overrides"]

_LOGGER = logging.getLogger(__name__)


def league_tuning_overrides(
    data_dir: Path | str | None = None,
    *,
    generation: object | None = None,
    store: bool = True,
    migrate: bool = True,
) -> Dict[str, Any]:
    """The generation's profile with the league's stored overrides over it.

    ``data_dir`` is a league data directory other than the current league
    (``None``: the current league). ``generation`` is the season's engine
    generation when the caller already has it (a parallel-day worker gets
    its parent's); otherwise it is read, and with ``store`` fixed for the
    season -- pass ``store`` False for anything that is not a season game.
    ``migrate`` False reads the overrides file without ever rewriting it (a
    lineup action must not change a tuning file).

    A stored override wins over the profile. An overrides file that cannot
    be read leaves the profile alone, as it used to leave the defaults
    alone. A generation whose profile cannot be loaded raises: a season on
    the new engine is never played on the old one in silence.
    """

    if generation is None:
        if data_dir is None:
            generation = get_league_engine_generation(store=store)
        else:
            generation = league_engine_generation(Path(data_dir), store=store)
    number = normalize_engine_generation(generation)
    overrides: Dict[str, Any] = engine_profile(number)
    path = (
        None
        if data_dir is None
        else Path(data_dir) / physics_tuning_settings.TUNING_OVERRIDES_FILENAME
    )
    try:
        overrides.update(
            physics_tuning_settings.get_physics_tuning_overrides(
                number, path=path, migrate=migrate
            )
        )
    except Exception:  # a game must still run
        _LOGGER.exception("could not read the league's tuning overrides")
    return overrides


def league_tuning(
    data_dir: Path | str | None = None,
    *,
    store: bool = False,
    migrate: bool = False,
):
    """A league's whole tuning (all four layers) as a ``TuningConfig``.

    Read-only by default: for reports and tools, not for playing a season
    game (``playbalance.game_runner`` layers the pieces itself, with the
    injury settings and the extra-innings rule between them).
    """

    from physics_sim.config import load_tuning

    overrides = league_tuning_overrides(data_dir, store=store, migrate=migrate)
    try:
        overrides.update(league_rating_centers(data_dir, store=store))
    except Exception:  # pragma: no cover - defensive
        _LOGGER.exception("could not read the league's rating centres")
    return load_tuning(overrides)
