"""
Find this NFL week's DraftKings Classic draft group ID automatically, so the
daily/weekly pulls don't stall waiting for a hand-pasted curl.

The slate the pipeline uses is the full-week Classic slate (Thu night through
Monday night, every game) -- e.g. Week 9 = 155993 (15 games), Week 10 = 156415
(14 games). DK only lists that group in its public lobby until the Thursday
game locks; after that it drops out of the lobby but is still served by the
draftgroups API. So this script:

  1. Reads the lobby (www.draftkings.com/lobby/getcontests?sport=NFL) and
     collects every Classic (contestTypeId 21) draft group ID.
  2. Also probes a small range of IDs just below the lowest lobby ID, which is
     where the already-locked full-week group sits (it's created first).
  3. Keeps Classic groups whose games all fall inside the current NFL week
     window (reference/nfl_2026_calendar.csv) and picks the one with the most
     games (tie -> earliest start, then lowest ID).

Usage:
    python scripts\\find_dk_draft_group.py              # prints the ID
    python scripts\\find_dk_draft_group.py --verbose    # shows every candidate
    python scripts\\find_dk_draft_group.py --json       # {"week": N, "draft_group_id": ...}

Exits 2 (printing nothing on stdout) if no draft group for this week is found
yet -- e.g. early Tuesday, before DK posts the week's slates.
"""
import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nfl_calendar import current_week, week_for_date  # noqa: E402
from pull_dk_salaries import HEADERS  # noqa: E402

CLASSIC_CONTEST_TYPE = 21
PROBE_BELOW = 25  # how far under the lowest lobby ID to look for a locked full-week group


def log(msg, verbose):
    if verbose:
        print(msg, file=sys.stderr)


def lobby_classic_ids():
    r = requests.get("https://www.draftkings.com/lobby/getcontests",
                     params={"sport": "NFL"}, headers=HEADERS, timeout=30)
    r.raise_for_status()
    groups = r.json().get("DraftGroups", []) or []
    return sorted({g["DraftGroupId"] for g in groups
                   if g.get("ContestTypeId") == CLASSIC_CONTEST_TYPE and g.get("DraftGroupId")})


def fetch_group(gid):
    r = requests.get(f"https://api.draftkings.com/draftgroups/v1/{gid}", headers=HEADERS, timeout=20)
    if r.status_code != 200:
        return None
    return r.json().get("draftGroup")


def _et_date(ts):
    # DK times are UTC ("2026-11-17T01:15:00.0000000Z"). Shifting by -5h puts
    # every NFL kickoff (9:30 AM London through 8:20 PM night games) on its
    # correct US calendar date in both EDT and EST.
    dt = datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S")
    return (dt - timedelta(hours=5)).date()


def find(as_of=None, verbose=False):
    wk = week_for_date(as_of) if as_of else current_week()
    if wk is None:
        log("Today isn't inside a known NFL week.", verbose)
        return None, None

    lobby = lobby_classic_ids()
    log(f"Week {wk.week} window {wk.window_start}..{wk.window_end}; lobby classic IDs: {lobby}", verbose)
    if not lobby:
        return wk.week, None

    candidates = []
    seen = set()

    def consider(gid):
        if gid in seen:
            return False
        seen.add(gid)
        g = fetch_group(gid)
        if not g or (g.get("contestType") or {}).get("contestTypeId") != CLASSIC_CONTEST_TYPE:
            return False
        if ((g.get("leagues") or [{}])[0] or {}).get("leagueAbbreviation") != "NFL":
            return False
        games = g.get("games") or []
        dates = [_et_date(x["startDate"]) for x in games if x.get("startDate")]
        if not dates or g.get("draftGroupState") in ("Historical", "Completed", "Cancelled"):
            return False
        in_week = all(wk.window_start <= d <= wk.window_end for d in dates)
        log(f"  {gid}: {len(games)} games, {min(dates)}..{max(dates)}, "
            f"state={g.get('draftGroupState')}{'' if in_week else '  (outside week window)'}", verbose)
        if in_week:
            candidates.append((-len(games), g.get("minStartTime") or "", gid))
        return in_week

    in_week_lobby = [gid for gid in lobby if consider(gid)]
    if not in_week_lobby:
        return wk.week, None
    # The full-week group is created before the per-day slates, so once it
    # drops out of the lobby (Thursday lock) it sits just below them.
    anchor = min(in_week_lobby)
    log(f"Probing {anchor - PROBE_BELOW}..{anchor - 1} for a locked full-week group...", verbose)
    for gid in range(anchor - 1, anchor - PROBE_BELOW - 1, -1):
        consider(gid)

    if not candidates:
        return wk.week, None
    candidates.sort()
    return wk.week, candidates[0][2]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD to resolve the NFL week for (default today)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    as_of = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else None
    week, gid = find(as_of, args.verbose)
    if args.json:
        print(json.dumps({"week": week, "draft_group_id": gid}))
    elif gid is not None:
        print(gid)
    if gid is None:
        print(f"No DK Classic draft group found yet for week {week}.", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
