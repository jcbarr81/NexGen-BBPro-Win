#!/usr/bin/env python3
"""Build the NexGen-BBPro executable and installer."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import pathlib
import re
import shutil
import subprocess
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "VERSION"
ISS_FILE = ROOT / "packaging" / "NexGen-BBPro.iss"
BUILD_EXE = ROOT / "build_exe.py"
VALIDATE_RELEASE = ROOT / "scripts" / "validate_finance_release.py"
RELEASE_NOTES_FILE = ROOT / "release_notes.md"
DRAFT_NOTES_FILE = ROOT / "release_notes_draft.md"
LAST_BUILD_RE = re.compile(r"^<!--\s*last_build_ref:\s*([0-9a-fA-F]+)\s*-->$")
CHECKLIST_PASS_TOKEN = "Checklist Result: PASS"


def read_version() -> str:
    if not VERSION_FILE.exists():
        raise FileNotFoundError(f"VERSION file not found at {VERSION_FILE}")
    version = VERSION_FILE.read_text(encoding="utf-8").strip()
    if not version:
        raise ValueError("VERSION file is empty")
    return version


def update_iss_version(version: str) -> bool:
    if not ISS_FILE.exists():
        raise FileNotFoundError(f"Installer script not found at {ISS_FILE}")
    lines = ISS_FILE.read_text(encoding="utf-8").splitlines()
    updated = False
    found = False
    new_lines: list[str] = []
    target = f"AppVersion={version}"

    for line in lines:
        if line.startswith("AppVersion="):
            found = True
            if line != target:
                updated = True
                new_lines.append(target)
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    if not found:
        raise ValueError("AppVersion entry not found in installer script")

    if updated:
        ISS_FILE.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    return updated


def find_iscc(explicit: str | None) -> str:
    if explicit:
        return explicit

    env_home = os.environ.get("INNO_SETUP_HOME")
    if env_home:
        candidate = pathlib.Path(env_home) / "ISCC.exe"
        if candidate.exists():
            return str(candidate)

    which = shutil.which("ISCC.exe") or shutil.which("ISCC")
    if which:
        return which

    candidates = [
        pathlib.Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
        pathlib.Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
        pathlib.Path(r"C:\Program Files (x86)\Inno Setup 5\ISCC.exe"),
        pathlib.Path(r"C:\Program Files\Inno Setup 5\ISCC.exe"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    raise FileNotFoundError(
        "ISCC.exe not found. Install Inno Setup or pass --iscc /path/to/ISCC.exe"
    )


def run_command(cmd: list[str], cwd: pathlib.Path | None = None) -> None:
    print("Running:", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=cwd or ROOT, check=True)


def validate_ui_checklist_artifact(path: pathlib.Path, *, version: str) -> None:
    if not path.exists():
        raise FileNotFoundError(
            f"UI checklist artifact not found: {path}. "
            "Run scripts/archive_ui_checklist.py after manual checklist execution."
        )
    text = path.read_text(encoding="utf-8")
    if CHECKLIST_PASS_TOKEN not in text:
        raise ValueError(
            f"UI checklist artifact must include '{CHECKLIST_PASS_TOKEN}'."
        )
    version_marker = f"v{version}"
    if version_marker not in text and f"Version: {version}" not in text:
        raise ValueError(
            f"UI checklist artifact does not appear to reference release version {version}."
        )


def run_git(args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git command failed")
    return result.stdout.strip()


def read_last_build_ref() -> str | None:
    if not RELEASE_NOTES_FILE.exists():
        return None
    for line in RELEASE_NOTES_FILE.read_text(encoding="utf-8").splitlines():
        match = LAST_BUILD_RE.match(line)
        if match:
            return match.group(1)
    return None


def get_latest_tag() -> str | None:
    try:
        tag = run_git(["describe", "--tags", "--abbrev=0"])
    except RuntimeError:
        return None
    return tag or None


def sanitize_ascii(text: str) -> str:
    return text.encode("ascii", "replace").decode("ascii")


def gather_changes(base_ref: str | None) -> list[str]:
    if base_ref:
        args = ["log", f"{base_ref}..HEAD", "--pretty=format:%s"]
    else:
        args = ["log", "--pretty=format:%s"]
    try:
        output = run_git(args)
    except RuntimeError as exc:
        return [f"Unable to collect git log ({sanitize_ascii(str(exc))})."]
    if not output:
        return []
    return [sanitize_ascii(line.strip()) for line in output.splitlines() if line.strip()]


def read_draft_notes() -> list[str]:
    if not DRAFT_NOTES_FILE.exists():
        return []

    notes: list[str] = []
    for raw_line in DRAFT_NOTES_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            continue
        if line.startswith("- "):
            line = line[2:].strip()
        notes.append(sanitize_ascii(line))
    return notes


def clear_draft_notes() -> None:
    if DRAFT_NOTES_FILE.exists():
        DRAFT_NOTES_FILE.write_text("", encoding="utf-8")


def write_release_notes(version: str, clear_draft: bool = True) -> None:
    last_build_ref = read_last_build_ref()
    base_ref = last_build_ref or get_latest_tag()
    if last_build_ref:
        base_label = f"last build {last_build_ref[:7]}"
    elif base_ref:
        base_label = base_ref
    else:
        base_label = "initial commit"

    notes = gather_changes(base_ref)
    draft_notes = read_draft_notes()
    if draft_notes:
        notes.extend(draft_notes)
    if not notes:
        notes = ["No changes since last build and no draft notes were found."]

    today = dt.date.today().isoformat()
    section_lines = [
        f"# {version} Release Notes (Since {base_label})",
        f"Date: {today}",
        "",
    ]
    section_lines.extend(f"- {note}" for note in notes)

    head_ref = None
    try:
        head_ref = run_git(["rev-parse", "HEAD"])
    except RuntimeError:
        head_ref = "unknown"

    marker = f"<!-- last_build_ref: {head_ref} -->"

    existing: list[str] = []
    if RELEASE_NOTES_FILE.exists():
        existing = RELEASE_NOTES_FILE.read_text(encoding="utf-8").splitlines()
        existing = [line for line in existing if not LAST_BUILD_RE.match(line)]

    content: list[str] = [marker]
    content.extend(existing)
    if content and content[-1].strip():
        content.append("")
    content.extend(section_lines)
    content.append("")

    RELEASE_NOTES_FILE.write_text("\n".join(content), encoding="utf-8")
    if clear_draft:
        clear_draft_notes()


def clean_outputs() -> None:
    for folder in (ROOT / "build", ROOT / "dist"):
        if folder.exists():
            shutil.rmtree(folder)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Build the NexGen-BBPro exe and installer.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove build/ and dist/ before building",
    )
    parser.add_argument(
        "--skip-exe",
        action="store_true",
        help="Skip running PyInstaller",
    )
    parser.add_argument(
        "--skip-installer",
        action="store_true",
        help="Skip running Inno Setup",
    )
    parser.add_argument(
        "--skip-iss",
        action="store_true",
        help="Skip updating AppVersion in the .iss file",
    )
    parser.add_argument(
        "--skip-notes",
        action="store_true",
        help="Skip updating release_notes.md",
    )
    parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="Skip pre-build finance release validation checks.",
    )
    parser.add_argument(
        "--validation-seasons",
        type=int,
        default=8,
        help="Season count for strict finance stability validation.",
    )
    parser.add_argument(
        "--validation-seed",
        type=int,
        default=42,
        help="Seed for finance stability validation.",
    )
    parser.add_argument(
        "--validation-preset",
        default="standard",
        help="Finance preset used during validation stability simulation.",
    )
    parser.add_argument(
        "--validation-max-fa-rounds",
        type=int,
        default=0,
        help="Optional cap for validation free-agency rounds (0 = auto).",
    )
    parser.add_argument(
        "--validation-report-dir",
        help="Directory for validation JSON/CSV outputs.",
    )
    parser.add_argument(
        "--keep-draft-notes",
        action="store_true",
        help="Do not clear release_notes_draft.md after appending its entries",
    )
    parser.add_argument(
        "--iscc",
        help="Path to ISCC.exe (Inno Setup compiler)",
    )
    parser.add_argument(
        "--require-ui-checklist",
        action="store_true",
        help=(
            "Require a manual UI/installer checklist artifact with PASS status "
            "before building."
        ),
    )
    parser.add_argument(
        "--ui-checklist-artifact",
        help=(
            "Path to archived manual checklist markdown. "
            "Used when --require-ui-checklist is enabled."
        ),
    )
    args = parser.parse_args(argv)

    if args.clean:
        clean_outputs()

    version = read_version()

    if args.require_ui_checklist:
        if not args.ui_checklist_artifact:
            raise ValueError(
                "--require-ui-checklist requires --ui-checklist-artifact <path>."
            )
        validate_ui_checklist_artifact(
            pathlib.Path(args.ui_checklist_artifact),
            version=version,
        )
        print("Manual UI/installer checklist artifact validated.")


    if not args.skip_validation:
        validate_cmd = [
            sys.executable,
            str(VALIDATE_RELEASE),
            "--seasons",
            str(max(1, int(args.validation_seasons))),
            "--seed",
            str(int(args.validation_seed)),
            "--preset",
            str(args.validation_preset),
        ]
        if int(args.validation_max_fa_rounds) > 0:
            validate_cmd.extend(
                ["--max-fa-rounds", str(int(args.validation_max_fa_rounds))]
            )
        if args.validation_report_dir:
            validate_cmd.extend(["--report-dir", str(args.validation_report_dir)])
        run_command(validate_cmd)
        print("Pre-build finance validation passed.")

    if not args.skip_iss:
        changed = update_iss_version(version)
        if changed:
            print(f"Updated AppVersion in {ISS_FILE.name} to {version}.")
        else:
            print(f"AppVersion already matches VERSION ({version}).")

    if not args.skip_notes:
        write_release_notes(version, clear_draft=not args.keep_draft_notes)
        print(f"Updated {RELEASE_NOTES_FILE.name} for {version}.")

    if not args.skip_exe:
        run_command([sys.executable, str(BUILD_EXE)])

    if not args.skip_installer:
        iscc = find_iscc(args.iscc)
        run_command([iscc, str(ISS_FILE)])

    print("Build complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
