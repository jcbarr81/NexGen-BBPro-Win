#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from playbalance.season_simulator import SeasonSimulator
from playbalance.game_runner import simulate_game_scores
from utils.path_utils import get_base_dir
from utils.stats_persistence import load_stats as load_season_stats
from utils.pitcher_recovery import PitcherRecoveryTracker


@dataclass
class RoleSummary:
    count: int = 0
    g: float = 0.0
    ip: float = 0.0
    gs: float = 0.0

    def add(self, g: float, ip: float, gs: float = 0.0) -> None:
        self.g += g
        self.ip += ip
        self.gs += gs
        self.count += 1

    @property
    def avg_g(self) -> float:
        return self.g / self.count if self.count else 0.0

    @property
    def avg_ip(self) -> float:
        return self.ip / self.count if self.count else 0.0

    @property
    def avg_gs(self) -> float:
        return self.gs / self.count if self.count else 0.0

    @property
    def ip_per_g(self) -> float:
        return self.ip / self.g if self.g else 0.0

    @property
    def ip_per_gs(self) -> float:
        return self.ip / self.gs if self.gs else 0.0


def _load_schedule(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = [dict(r) for r in reader]
        for r in rows:
            # normalize keys
            r["date"] = r.get("date") or r.get("game_date") or r.get("GameDate")
            r["home"] = r.get("home") or r.get("home_id") or r.get("Home")
            r["away"] = r.get("away") or r.get("away_id") or r.get("Away")
            if not r["date"] or not r["home"] or not r["away"]:
                raise ValueError("Schedule file must have date, home, away columns")
        return rows


def _role_map_from_rosters(roster_dir: Path) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for f in roster_dir.glob("*_pitching.csv"):
        with f.open(newline="", encoding="utf-8") as fh:
            reader = csv.reader(fh)
            for row in reader:
                if len(row) < 2:
                    continue
                pid = row[0].strip()
                role = row[1].strip().upper()
                if pid and role:
                    mapping[pid] = role
    return mapping


def _bucket_role(role: str) -> str:
    role = (role or "").upper()
    if role.startswith("SP"):
        return "SP"
    if role in {"LR", "MR", "SU", "CL"}:
        return role
    return "RP"


def _summarize_by_role(players: Dict[str, dict], roster_roles: Dict[str, str]) -> Dict[str, RoleSummary]:
    summary: Dict[str, RoleSummary] = defaultdict(RoleSummary)
    for pid, pdata in players.items():
        # Restrict to the pitching staff (as defined by *_pitching.csv mapping)
        if pid not in roster_roles:
            continue
        role = _bucket_role(roster_roles.get(pid, pdata.get("role", "")))
        g = float(pdata.get("g", 0) or 0)
        ip = float(pdata.get("ip", 0) or 0)
        gs = float(pdata.get("gs", 0) or 0)
        summary[role].add(g, ip, gs)
    return summary


def _list_shards(shards_dir: Path) -> List[Path]:
    if not shards_dir.exists():
        return []
    files = [p for p in shards_dir.glob("*.json") if p.is_file()]
    files.sort()
    return files


def _summarize_appearances_from_shards(shards_dir: Path, roster_roles: Dict[str, str]) -> Dict[str, RoleSummary]:
    """Compute role averages from daily shards using per-pitcher deltas.

    For each pitcher, we sum daily IP increments and count an appearance on any
    day where IP increased. Then aggregate by role and average per unique pitcher.
    """
    shards = _list_shards(shards_dir)
    # Track last IP per pitcher and accumulate totals per pitcher
    last_ip: Dict[str, float] = {}
    per_pid: Dict[str, Tuple[str, float, float]] = {}  # pid -> (role, apps, ip)

    for shard in shards:
        try:
            with shard.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            continue
        players = data.get("players", {}) or {}
        for pid, pdata in players.items():
            if pid not in roster_roles:
                continue
            role = _bucket_role(roster_roles.get(pid, pdata.get("role", "")))
            ip = float(pdata.get("ip", 0) or 0)
            prev = last_ip.get(pid, 0.0)
            inc = ip - prev
            app = 1.0 if inc > 0 else 0.0
            last_ip[pid] = ip
            old_role, a, total_ip = per_pid.get(pid, (role, 0.0, 0.0))
            # Role can change rarely; prefer roster-assigned role
            per_pid[pid] = (role or old_role, a + app, total_ip + (inc if inc > 0 else 0.0))

    # Aggregate by role with unique pitcher counts
    out: Dict[str, RoleSummary] = defaultdict(RoleSummary)
    for pid, (role, apps, ip) in per_pid.items():
        rs = out[role]
        rs.count += 1
        rs.g += apps
        rs.ip += ip
    return out


def _summarize_cadence_from_shards(shards_dir: Path, roster_roles: Dict[str, str]) -> Tuple[Dict[str, float], Dict[str, float], Dict[str, float]]:
    """Return role-level cadence metrics from shards.

    - avg_max7: average of per-pitcher max appearances in any 7-day window
    - pct_3in4: percent of pitchers who had at least one 3-appearances-in-4-days stretch
    - b2b_rate: average of per-pitcher back-to-back rate (apps where prev day also had an app)
    """
    shards = _list_shards(shards_dir)
    # Gather appearance dates per pid
    last_ip: Dict[str, float] = {}
    apps: Dict[str, List[date]] = {}

    for shard in shards:
        try:
            with shard.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            continue
        dstr = str(data.get("date") or "")
        try:
            d = datetime.strptime(dstr, "%Y-%m-%d").date()
        except Exception:
            # Fallback to shard filename-derived ordering if date missing
            try:
                d = datetime.strptime(shard.stem, "%Y-%m-%d").date()
            except Exception:
                continue
        players = data.get("players", {}) or {}
        for pid, pdata in players.items():
            if pid not in roster_roles:
                continue
            ip = float(pdata.get("ip", 0) or 0)
            prev = last_ip.get(pid, 0.0)
            if ip > prev:
                apps.setdefault(pid, []).append(d)
            last_ip[pid] = ip

    # Compute per-pitcher metrics, then aggregate by role
    per_role_vals: Dict[str, List[Tuple[float, float, float]]] = {}
    # tuple = (max7, has_3in4 (0/1), b2b_rate)

    for pid, dates in apps.items():
        if pid not in roster_roles:
            continue
        role = _bucket_role(roster_roles.get(pid, ""))
        if not dates:
            continue
        dates.sort()
        # B2B count
        b2b = 0
        for i in range(1, len(dates)):
            if (dates[i] - dates[i - 1]).days == 1:
                b2b += 1
        b2b_rate = b2b / max(len(dates) - 1, 1)

        # Max appearances in any 7-day window
        max7 = 0
        start = 0
        for end in range(len(dates)):
            while start <= end and (dates[end] - dates[start]).days > 6:
                start += 1
            window = end - start + 1
            if window > max7:
                max7 = window
        # 3-in-4 occurrences (has at least one window of size >=3 over 4 days)
        has_3in4 = 0.0
        start = 0
        for end in range(len(dates)):
            while start <= end and (dates[end] - dates[start]).days > 3:
                start += 1
            if end - start + 1 >= 3:
                has_3in4 = 1.0
                break
        per_role_vals.setdefault(role, []).append((float(max7), has_3in4, float(b2b_rate)))

    def _avg(lst: List[float]) -> float:
        return sum(lst) / len(lst) if lst else 0.0

    avg_max7: Dict[str, float] = {}
    pct_3in4: Dict[str, float] = {}
    b2b_rate: Dict[str, float] = {}
    for role, vals in per_role_vals.items():
        max7_list = [v[0] for v in vals]
        has_list = [v[1] for v in vals]
        b2b_list = [v[2] for v in vals]
        avg_max7[role] = _avg(max7_list)
        pct_3in4[role] = (sum(has_list) / len(has_list)) * 100 if has_list else 0.0
        b2b_rate[role] = _avg(b2b_list)
    return avg_max7, pct_3in4, b2b_rate


def _print_summary(summary: Dict[str, RoleSummary]) -> None:
    print("Role usage summary (avg per pitcher):")
    print("role,count,avg_g,avg_gs,avg_ip,ip_per_g,ip_per_gs")
    for role in ("SP", "CL", "SU", "MR", "LR", "RP"):
        s = summary.get(role)
        if not s:
            continue
        print(
            f"{role},{s.count},{s.avg_g:.1f},{s.avg_gs:.1f},{s.avg_ip:.1f},{s.ip_per_g:.2f},{s.ip_per_gs:.2f}"
        )


def main() -> None:
    ap = argparse.ArgumentParser(description="Simulate a schedule and summarize pitcher usage by role.")
    ap.add_argument("--schedule", type=str, required=True, help="CSV with columns: date,home,away")
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument("--players_file", type=str, default=str(get_data_dir() / "players.csv"))
    ap.add_argument("--roster_dir", type=str, default=str(get_data_dir() / "rosters"))
    args = ap.parse_args()

    schedule_path = Path(args.schedule)
    schedule = _load_schedule(schedule_path)

    # Build a season simulator using the default game function
    tracker = PitcherRecoveryTracker.instance()
    tracker.refresh_config()
    tracker.save = lambda *args, **kwargs: None  # disable disk persistence for calibration runs
    sim = SeasonSimulator(schedule)
    # Simulate all scheduled days
    for _ in range(sim.remaining_schedule_days()):
        sim.simulate_next_day()

    # Load season stats and summarize by role
    roster_roles = _role_map_from_rosters(Path(args.roster_dir))
    # Prefer shard-based appearance counting for more realistic G/IP
    shards_dir = get_data_dir() / "season_history"
    summary = _summarize_appearances_from_shards(shards_dir, roster_roles)
    if not summary:
        # Fallback to raw season totals
        stats = load_season_stats()
        players = stats.get("players", {}) or {}
        summary = _summarize_by_role(players, roster_roles)
    _print_summary(summary)

    # Cadence metrics from shards (may be limited if shard dates are not unique)
    avg_max7, pct_3in4, b2b_rate = _summarize_cadence_from_shards(shards_dir, roster_roles)
    print("\nRole cadence summary (from shards; may be limited by shard dating):")
    print("role,avg_max7,pct_3in4,b2b_rate")
    for role in ("SP", "CL", "SU", "MR", "LR", "RP"):
        if role not in summary:
            continue
        print(f"{role},{avg_max7.get(role, 0):.2f},{pct_3in4.get(role, 0):.1f}%,{b2b_rate.get(role, 0):.2f}")

    # Cadence metrics from PitcherRecoveryTracker (robust daily dating)
    print("\nRole cadence summary (from recovery tracker):")
    try:
        rec = PitcherRecoveryTracker.instance()
        rec.refresh_config()
        teams = rec.data.get("teams", {}) or {}
        per_pid_dates: Dict[str, List[date]] = {}
        per_pid_role: Dict[str, str] = {}
        # Compute schedule date bounds to filter tracker history
        sched_dates = [datetime.strptime(str(r["date"]), "%Y-%m-%d").date() for r in schedule]
        min_d = min(sched_dates) if sched_dates else None
        max_d = max(sched_dates) if sched_dates else None
        for team_id, entry in teams.items():
            pitchers = entry.get("pitchers", {}) or {}
            for pid, payload in pitchers.items():
                recent = payload.get("recent", []) or []
                role = payload.get("last_role") or roster_roles.get(pid, "")
                role = _bucket_role(str(role))
                per_pid_role[pid] = role
                for r in recent:
                    if not r.get("appeared"):
                        continue
                    dstr = str(r.get("date") or "")
                    try:
                        d = datetime.strptime(dstr, "%Y-%m-%d").date()
                    except Exception:
                        continue
                    if (min_d is None or d >= min_d) and (max_d is None or d <= max_d):
                        per_pid_dates.setdefault(pid, []).append(d)
        # Compute same metrics
        role_vals: Dict[str, List[Tuple[float, float, float]]] = {}
        for pid, dates in per_pid_dates.items():
            role = per_pid_role.get(pid) or "RP"
            dates = sorted(set(dates))
            if not dates:
                continue
            b2b = sum(1 for i in range(1, len(dates)) if (dates[i] - dates[i - 1]).days == 1)
            b2b_rate = b2b / max(len(dates) - 1, 1)
            # max7
            max7 = 0
            s = 0
            for e in range(len(dates)):
                while s <= e and (dates[e] - dates[s]).days > 6:
                    s += 1
                max7 = max(max7, e - s + 1)
            # 3-in-4
            has_3 = 0.0
            s = 0
            for e in range(len(dates)):
                while s <= e and (dates[e] - dates[s]).days > 3:
                    s += 1
                if e - s + 1 >= 3:
                    has_3 = 1.0
                    break
            role_vals.setdefault(role, []).append((float(max7), has_3, float(b2b_rate)))
        def _avg(lst: List[float]) -> float:
            return sum(lst) / len(lst) if lst else 0.0
        roles = ("SP", "CL", "SU", "MR", "LR", "RP")
        print("role,avg_max7,pct_3in4,b2b_rate")
        for role in roles:
            vals = role_vals.get(role, [])
            max7_list = [v[0] for v in vals]
            has_list = [v[1] for v in vals]
            b2b_list = [v[2] for v in vals]
            avg7 = _avg(max7_list)
            pct3 = (sum(has_list) / len(has_list)) * 100 if has_list else 0.0
            b2br = _avg(b2b_list)
            if role in summary:
                print(f"{role},{avg7:.2f},{pct3:.1f}%,{b2br:.2f}")
    except Exception:
        print("(Recovery tracker metrics unavailable)")


if __name__ == "__main__":
    main()
