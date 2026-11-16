"""
Download nflverse's free weekly snap counts and player stats -- no API key.

Why (Jake, 2026-11-16): our PFF subscription only reports a player's snaps
when he records a catch, so a salary saver who played 40 snaps with 0
catches looks the same as one who never left the bench. nflverse's
snap_counts (from Pro Football Reference) lists every player who took an
offensive snap, and stats_player_week has targets. build_projections.py
uses both for the punt check (see PUNT_* there) and for the "heavy 12
personnel" team list (TE snaps per offensive play).

Usage:
    python scripts\\pull_nflverse_usage.py --season 2026

Writes (overwritten each run; nflverse refreshes these within a day or so
of each game):
    data\\nflverse\\snap_counts_{season}.csv
    data\\nflverse\\stats_player_week_{season}.csv
"""
import argparse
import sys
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = PROJECT_ROOT / "data" / "nflverse"
BASE = "https://github.com/nflverse/nflverse-data/releases/download"
FILES = {
    "snap_counts_{season}.csv": "snap_counts/snap_counts_{season}.csv",
    "stats_player_week_{season}.csv": "stats_player/stats_player_week_{season}.csv",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, required=True)
    args = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    failed = False
    for local, remote in FILES.items():
        url = f"{BASE}/{remote.format(season=args.season)}"
        dest = OUT_DIR / local.format(season=args.season)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "pff-dfs-tools"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()
        except Exception as e:  # keep going -- build_projections skips the punt check without it
            print(f"[warn] couldn't download {url}: {e}")
            failed = True
            continue
        dest.write_bytes(data)
        lines = data.count(b"\n")
        print(f"Wrote {dest} ({lines:,} rows)")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
