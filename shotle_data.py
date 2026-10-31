#!/usr/bin/env python3
"""Build shotle-data.json from stats.nba.com (regular season, one season for shots and roster).

    pip install nba_api pandas
    python shotle_data.py --season 2025-26

Raw responses are frozen in shotle_cache/, so reruns make no NBA requests. Use --refresh to refetch.
"""
import argparse
import calendar
import json
import math
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
from nba_api.stats.endpoints import leaguedashplayerstats, playerindex, shotchartdetail

HY = 5.25
ROW_CAP = 102400
NAME_FIX = {"alperen-sengun": "Alperen Şengün"}
# one label per position pair, so F-G and G-F never count as different
POS_FIX = {"F-G": "G-F", "C-F": "F-C"}
# known players who missed the games or shot volume for the answer pool
ANSWER_EXTRA = {"jayson-tatum", "ja-morant", "domantas-sabonis", "anthony-davis", "paul-george"}
EMBED = re.compile(r'(<script id="shotle-data" type="application/json">).*?(</script>)', re.S)
ZONES =["ra", "pt", "m0", "m1", "m2", "m3", "m4", "cl", "cr", "a0", "a1", "a2", "a3", "a4"]

# abbreviation: full name, conference, division
TEAMS = {
    "BOS": ["Boston Celtics", "D", "Atl"], "BKN": ["Brooklyn Nets", "D", "Atl"],
    "NYK": ["New York Knicks", "D", "Atl"], "PHI": ["Philadelphia 76ers", "D", "Atl"],
    "TOR": ["Toronto Raptors", "D", "Atl"], "CHI": ["Chicago Bulls", "D", "Cen"],
    "CLE": ["Cleveland Cavaliers", "D", "Cen"], "DET": ["Detroit Pistons", "D", "Cen"],
    "IND": ["Indiana Pacers", "D", "Cen"], "MIL": ["Milwaukee Bucks", "D", "Cen"],
    "ATL": ["Atlanta Hawks", "D", "SE"], "CHA": ["Charlotte Hornets", "D", "SE"],
    "MIA": ["Miami Heat", "D", "SE"], "ORL": ["Orlando Magic", "D", "SE"],
    "WAS": ["Washington Wizards", "D", "SE"], "DEN": ["Denver Nuggets", "B", "NW"],
    "MIN": ["Minnesota Timberwolves", "B", "NW"], "OKC": ["Oklahoma City Thunder", "B", "NW"],
    "POR": ["Portland Trail Blazers", "B", "NW"], "UTA": ["Utah Jazz", "B", "NW"],
    "GSW": ["Golden State Warriors", "B", "Pac"], "LAC": ["LA Clippers", "B", "Pac"],
    "LAL": ["Los Angeles Lakers", "B", "Pac"], "PHX": ["Phoenix Suns", "B", "Pac"],
    "SAC": ["Sacramento Kings", "B", "Pac"], "DAL": ["Dallas Mavericks", "B", "SW"],
    "HOU": ["Houston Rockets", "B", "SW"], "MEM": ["Memphis Grizzlies", "B", "SW"],
    "NOP": ["New Orleans Pelicans", "B", "SW"], "SAS": ["San Antonio Spurs", "B", "SW"],
}


def zone_id(x, y):
    """Must match the zones drawn in index.html. 0 = right side, 4 = left side."""
    d = math.hypot(x, y - HY)
    if d < 4:
        return "ra"
    if abs(x) >= 22 and y < 14.2:
        return "cl" if x < 0 else "cr"
    ang = math.atan2(y - HY, x) * 180 / math.pi
    if ang < 0:
        ang = 180 if x < 0 else 0
    k = min(4, math.floor(ang / 36))
    if d >= 23.75:
        return f"a{k}"
    if abs(x) <= 8 and y < 19:
        return "pt"
    return f"m{k}"


def month_ranges(season):
    """First and last day of each month from October to June of a season such as 2025-26."""
    start = int(season[:4])
    for year, month in [(start, m) for m in range(10, 13)] + [(start + 1, m) for m in range(1, 7)]:
        yield date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def cached(path, fetch, refresh, delay):
    """Read a frozen response, or fetch it with retries and freeze it."""
    if path.exists() and not refresh:
        return pd.read_csv(path, keep_default_na=False, na_values=[""], low_memory=False)
    for attempt in range(4):
        try:
            df = fetch()
            path.parent.mkdir(exist_ok=True)
            df.to_csv(path, index=False)
            time.sleep(delay)
            return df
        except Exception as e:
            if attempt == 3:
                raise
            print(f"  retry {attempt + 1}: {type(e).__name__}")
            time.sleep(delay * 2 ** (attempt + 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default="2025-26")
    ap.add_argument("--top", type=int, default=150, help="answer pool: top N by attempts plus top N by minutes")
    ap.add_argument("--min-gp", type=int, default=30, help="games needed for the answer pool")
    ap.add_argument("--max-dist", type=float, default=40, help="drop heaves beyond this many feet")
    ap.add_argument("--delay", type=float, default=2)
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--out", default="shotle-data.json")
    ap.add_argument("--page", default="index.html")
    a = ap.parse_args()
    cache = Path("shotle_cache")

    stats = cached(cache / f"stats_{a.season}.csv", lambda: leaguedashplayerstats.LeagueDashPlayerStats(
        season=a.season, season_type_all_star="Regular Season", per_mode_detailed="Totals", timeout=a.timeout
    ).get_data_frames()[0], a.refresh, a.delay)
    print(f"stats: {len(stats)} players")

    # without historical=1 the index for a past season silently leaves out most players
    index = cached(cache / f"index_{a.season}.csv", lambda: playerindex.PlayerIndex(
        season=a.season, historical_nullable="1", timeout=a.timeout
    ).get_data_frames()[0], a.refresh, a.delay)
    print(f"index: {len(index)} players")

    # player_id=0 and team_id=0 return every shot, but one response stops at ROW_CAP rows, so fetch by month
    parts = []
    for first, last in month_ranges(a.season):
        part = cached(cache / f"shots_{a.season}_{first:%Y-%m}.csv", lambda: shotchartdetail.ShotChartDetail(
            team_id=0, player_id=0, season_nullable=a.season, season_type_all_star="Regular Season",
            context_measure_simple="FGA", date_from_nullable=f"{first:%m/%d/%Y}", date_to_nullable=f"{last:%m/%d/%Y}",
            timeout=a.timeout
        ).get_data_frames()[0], a.refresh, a.delay)
        if len(part) >= ROW_CAP:
            raise SystemExit(f"{first:%Y-%m} hit the row cap, shots are incomplete")
        print(f"  {first:%Y-%m}: {len(part)} attempts")
        parts.append(part)
    shots = pd.concat(parts).drop_duplicates(["GAME_ID", "GAME_EVENT_ID"])
    print(f"shots: {len(shots)} attempts, season total in stats: {int(stats.FGA.sum())}")
    if len(shots) != int(stats.FGA.sum()):
        print("  WARNING: shot total does not match the season FGA total")

    # NBA "left" is the shooter's left, which is the left of our chart (hoop at the bottom), so it must map to x<0
    left_corner = shots.loc[shots.SHOT_ZONE_BASIC == "Left Corner 3", "LOC_X"].mean()
    sign = 1 if left_corner < 0 else -1
    shots["x"] = sign * shots.LOC_X / 10
    shots["y"] = shots.LOC_Y / 10 + HY
    shots["dist"] = (shots.x ** 2 + (shots.y - HY) ** 2) ** 0.5
    kept = shots[shots.dist <= a.max_dist].copy()
    kept["zone"] = [zone_id(x, y) for x, y in zip(kept.x, kept.y)]

    league = kept.groupby("zone").SHOT_MADE_FLAG.agg(["sum", "count"])
    lg = {z: round(float(league.loc[z, "sum"] / league.loc[z, "count"]), 4) for z in ZONES}

    by_player = {}
    for (pid, zone), g in kept.groupby(["PLAYER_ID", "zone"]):
        by_player.setdefault(int(pid), {})[zone] = [int(g.SHOT_MADE_FLAG.sum()), int(len(g))]

    # everyone who played can be guessed; only answer players carry a shot chart
    regulars = stats[stats.GP >= a.min_gp]
    answer_ids = set(regulars.nlargest(a.top, "FGA").PLAYER_ID) | set(regulars.nlargest(a.top, "MIN").PLAYER_ID)

    idx = {int(r.PERSON_ID): r for r in index.itertuples()}
    players, skipped = [], []
    for r in stats.sort_values("FGA", ascending=False).itertuples():
        p = idx.get(int(r.PLAYER_ID))
        try:
            feet, inches = str(p.HEIGHT).split("-")
            team = r.TEAM_ABBREVIATION
            conf, div = TEAMS[team][1], TEAMS[team][2]
            pos = str(p.POSITION)
            if pos in ("", "nan"):
                raise ValueError("position")
            undrafted = pd.isna(p.DRAFT_YEAR) or pd.isna(p.DRAFT_NUMBER)
            player = {
                "id": p.PLAYER_SLUG, "nbaId": int(r.PLAYER_ID), "name": NAME_FIX.get(p.PLAYER_SLUG, r.PLAYER_NAME),
                "team": team, "conf": conf, "div": div, "pos": POS_FIX.get(pos, pos),
                "h": int(feet) * 12 + int(inches),
                "dy": None if undrafted else int(p.DRAFT_YEAR), "dp": None if undrafted else int(p.DRAFT_NUMBER),
                "gp": int(r.GP), "fga": int(r.FGA), "pts": int(r.PTS),
            }
        except (AttributeError, KeyError, ValueError) as e:
            skipped.append(r.PLAYER_NAME)
            print(f"  skipped {r.PLAYER_NAME}: {e!r}")
            continue
        if r.PLAYER_ID in answer_ids or p.PLAYER_SLUG in ANSWER_EXTRA:
            zones = by_player.get(int(r.PLAYER_ID), {})
            player["answer"] = True
            player["zones"] = {z: zones.get(z, [0, 0]) for z in ZONES}
        players.append(player)
    answers = sum(1 for p in players if p.get("answer"))

    out = {
        "meta": {
            "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "shotSeason": a.season, "rosterSeason": a.season, "seasonType": "Regular Season",
            "minGp": a.min_gp, "maxDist": a.max_dist, "shotsTotal": int(len(shots)),
            "shotsDropped": int(len(shots) - len(kept)),
            "nbaLeftCornerLocX": "negatif" if left_corner < 0 else "pozitif",
            "zones": ZONES, "leagueFg": lg, "answerCount": answers, "answerExtra": sorted(ANSWER_EXTRA),
            "skippedPlayers": skipped,
        },
        "teams": TEAMS,
        "players": players,
    }
    text = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
    Path(a.out).write_text(text, encoding="utf-8")
    print(f"wrote {a.out}: {len(players)} guessable, {answers} answers, skipped {skipped}")

    # the page carries its data inline, so it also works when opened straight from disk
    page = Path(a.page)
    if page.exists():
        html, n = EMBED.subn(lambda m: m.group(1) + text + m.group(2), page.read_text(encoding="utf-8"))
        if n != 1:
            raise SystemExit(f"data block not found in {page}")
        page.write_text(html, encoding="utf-8")
        print(f"embedded into {page}")


if __name__ == "__main__":
    main()
