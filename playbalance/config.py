"""Configuration loader for the play-balance engine.

This module reads tuning values from the project's ``PBINI.txt`` file.  The
file follows a simple INI-style structure and all entries are exposed through
the :class:`PlayBalanceConfig` dataclass.  An optional JSON file may supply
override values without touching the original configuration.
"""

from __future__ import annotations

from dataclasses import dataclass, field, make_dataclass
from pathlib import Path
from typing import Any, Dict
import json

from .pbini_loader import load_pbini
from utils.path_utils import get_data_dir, resolve_app_path


@dataclass
class PlayBalanceConfig:
    """Container for configuration sections loaded from ``PBINI.txt``.

    Each section from the INI file is converted into its own dataclass where
    every key becomes a typed attribute.  This provides attribute completion
    while still allowing dynamic loading of the configuration file.  The raw
    sections are preserved in :attr:`sections` for introspection.
    """

    sections: Dict[str, Any]

    def __post_init__(self) -> None:
        """Turn plain section dictionaries into dataclass instances."""

        typed_sections: Dict[str, Any] = {}
        for name, values in self.sections.items():
            fields = [(k, type(v), field(default=v)) for k, v in values.items()]
            SectionCls = make_dataclass(name, fields)
            section_obj = SectionCls(**values)
            setattr(self, name, section_obj)
            typed_sections[name] = section_obj
        self.sections = typed_sections

    # ------------------------------------------------------------------
    # Access helpers
    # ------------------------------------------------------------------
    def get(self, section: str, key: str, default: Any | None = None) -> Any:
        """Return a configuration value from ``section`` or ``default``."""

        sect = self.sections.get(section)
        return getattr(sect, key, default) if sect else default

    def __getattr__(self, item: str) -> Any:  # pragma: no cover - delegation
        """Expose ``PlayBalance`` entries as attributes returning ``0`` when
        missing."""

        sect = self.sections.get("PlayBalance")
        return getattr(sect, item, 0) if sect else 0

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------
    @classmethod
    def from_dict(cls, data: Dict[str, Dict[str, Any]]) -> "PlayBalanceConfig":
        """Create an instance from a nested ``data`` mapping."""

        return cls(dict(data))

    @classmethod
    def from_file(cls, path: str | Path) -> "PlayBalanceConfig":
        """Return configuration loaded from ``path``."""

        sections = load_pbini(path)
        return cls(sections)


def load_config(
    pbini_path: str | Path | None = None,
    overrides_path: str | Path | None = None,
) -> PlayBalanceConfig:
    """Load configuration from ``pbini_path`` and optional JSON overrides.

    Paths default to locations relative to the project root allowing the
    configuration to be loaded even when the current working directory is
    different from the repository location.
    """

    if pbini_path is None:
        pbini_path = resolve_app_path("playbalance/PBINI.txt")
    else:
        pbini_path = resolve_app_path(pbini_path)

    sections = load_pbini(pbini_path)
    # Preserve the original keys to ensure coverage after overrides are merged.
    pbini_keys = {sect: set(vals.keys()) for sect, vals in sections.items()}

    if overrides_path is None:
        overrides_path = get_data_dir() / "playbalance_overrides.json"
    else:
        overrides_path = resolve_app_path(overrides_path)

    if overrides_path.exists():
        try:
            with overrides_path.open("r", encoding="utf-8") as fh:
                overrides = json.load(fh)
        except json.JSONDecodeError:
            overrides = {}

        if isinstance(overrides, dict):
            # Determine which section should receive flat overrides.  By
            # convention the PBINI file uses a single "PlayBalance" section,
            # but fall back to the first loaded section for flexibility.
            default_section = "PlayBalance"
            if default_section not in sections and sections:
                default_section = next(iter(sections))

            for sect, values in overrides.items():
                if isinstance(values, dict):
                    if sect not in sections:
                        raise KeyError(f"Unknown config section '{sect}'")
                    unknown = set(values) - pbini_keys.get(sect, set())
                    if unknown:
                        unknown_list = ", ".join(sorted(unknown))
                        raise KeyError(f"Unknown keys for section '{sect}': {unknown_list}")
                    section_dict = sections.setdefault(sect, {})
                    section_dict.update(values)
                else:
                    # Allow flat overrides applied to the default section.
                    if sect not in pbini_keys.get(default_section, set()):
                        section_dict = sections.setdefault(default_section, {})
                        section_dict[sect] = values
                        pbini_keys.setdefault(default_section, set()).add(sect)
                        continue
                    section_dict = sections.setdefault(default_section, {})
                    section_dict[sect] = values

    # Ensure that all PBINI keys remain represented after merging overrides.
    for sect, keys in pbini_keys.items():
        missing = keys - set(sections.get(sect, {}).keys())
        if missing:
            missing_list = ", ".join(sorted(missing))
            raise KeyError(f"Missing keys from section '{sect}': {missing_list}")

    return PlayBalanceConfig(sections)


__all__ = ["PlayBalanceConfig", "load_config"]

