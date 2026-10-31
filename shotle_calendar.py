#!/usr/bin/env python3
"""Build puzzles.json, the daily player calendar, from shotle-data.json and embed it into index.html.

    python shotle_calendar.py

Same input and seed give the same calendar. Days up to and including today are kept from an
existing puzzles.json, so regenerating never changes a puzzle people may have played.
"""
import argparse
import json
import random
import re
from datetime import date, timedelta
from pathlib import Path

# color scale of zoneFill() in index.html, what the player sees before any guess
SMOOTH_K = 20
COLOR_RANGE = 0.16

# weekly mix of star (1), starter (2) and role player (3) days
WEEK = [2, 1, 3, 2, 1, 2, 3]
TIER1, TIER2 = 40, 60
MIN_GAP = 100
TEAM_GAP = 2
SIMILAR_BELOW = 0.18
EMBED = re.compile(r'(<script id="shotle-puzzles" type="application/json">).*?(</script>)', re.S)


def colors(p, zones, lg):
    """Heat value of each zone, 0 red, 0.5 yellow, 1 green."""
    out = []
    for z in zones:
        made, att = p["zones"][z]
        f = (made + SMOOTH_K * lg[z]) / (att + SMOOTH_K)
        out.append(max(0.0, min(1.0, 0.5 + (f - lg[z]) / COLOR_RANGE)))
    return out


def similar_counts(answers, zones, lg):
    """How many other answer players have a nearly identical colored chart."""
    vec = {p["id"]: colors(p, zones, lg) for p in answers}
    counts = {}
    for p in answers:
        a = vec[p["id"]]
        counts[p["id"]] = sum(
            1 for q in answers
            if q is not p and sum(abs(x - y) for x, y in zip(a, vec[q["id"]])) / len(a) < SIMILAR_BELOW
        )
    return counts


def assign_tiers(answers, extra):
    """Rank by points per game; known players short on games still count as stars."""
    ranked = sorted(answers, key=lambda p: (p["id"] not in extra, -p["pts"] / p["gp"], p["id"]))
    return {p["id"]: 1 if i < TIER1 else 2 if i < TIER1 + TIER2 else 3 for i, p in enumerate(ranked)}


def assign_difficulty(answers, tiers, similar):
    """Hard means little known and easy to confuse: terciles of tier plus similarity rank."""
    by_sim = sorted(answers, key=lambda p: (similar[p["id"]], p["id"]))
    sim_rank = {p["id"]: i / len(answers) for i, p in enumerate(by_sim)}
    scored = sorted(answers, key=lambda p: (tiers[p["id"]] + 2 * sim_rank[p["id"]], p["id"]))
    n = len(scored)
    return {p["id"]: "kolay" if i < n / 3 else "orta" if i < 2 * n / 3 else "zor" for i, p in enumerate(scored)}


def build(answers, tiers, difficulty, days, seed, kept):
    rng = random.Random(seed)
    team = {p["id"]: p["team"] for p in answers}
    decks = {1: [], 2: [], 3: []}
    out = list(kept)
    last = {pid: i for i, pid in enumerate(out)}
    for day in range(len(out), days):
        tier = WEEK[day % len(WEEK)]
        if not decks[tier]:
            decks[tier] = [p["id"] for p in answers if tiers[p["id"]] == tier]
            rng.shuffle(decks[tier])
        deck = decks[tier]

        def fits(pid, strict):
            if day - last.get(pid, -MIN_GAP) < MIN_GAP:
                return False
            if any(team[pid] == team[q] for q in out[-TEAM_GAP:]):
                return False
            return not (strict and out and difficulty[pid] == "zor" and difficulty[out[-1]] == "zor")

        pick = next((x for x in deck if fits(x, True)), None) or next((x for x in deck if fits(x, False)), None)
        if pick is None:
            # the rest of this deck is too recent, so take from a fresh shuffle
            fresh = [p["id"] for p in answers if tiers[p["id"]] == tier and p["id"] not in deck]
            rng.shuffle(fresh)
            pick = next((x for x in fresh if fits(x, False)), None)
            if pick is None:
                raise SystemExit(f"no candidate on day {day}")
            fresh.remove(pick)
            deck.extend(fresh)
        else:
            deck.remove(pick)
        out.append(pick)
        last[pick] = day
    return out


def check(ids, answers, tiers):
    known = {p["id"] for p in answers}
    team = {p["id"]: p["team"] for p in answers}
    last = {}
    for i, pid in enumerate(ids):
        assert pid in known, f"{pid} is not an answer player"
        assert pid not in last or i - last[pid] >= MIN_GAP, f"{pid} repeats on day {i}"
        assert all(team[pid] != team[q] for q in ids[max(0, i - TEAM_GAP):i]), f"team repeats on day {i}"
        last[pid] = i


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="shotle-data.json")
    ap.add_argument("--out", default="puzzles.json")
    ap.add_argument("--page", default="index.html")
    ap.add_argument("--start", default="2026-10-31")
    ap.add_argument("--days", type=int, default=730)
    ap.add_argument("--seed", type=int, default=20261031)
    a = ap.parse_args()

    data = json.loads(Path(a.data).read_text(encoding="utf-8"))
    zones, lg = data["meta"]["zones"], data["meta"]["leagueFg"]
    answers = [p for p in data["players"] if p.get("answer")]
    similar = similar_counts(answers, zones, lg)
    tiers = assign_tiers(answers, set(data["meta"]["answerExtra"]))
    difficulty = assign_difficulty(answers, tiers, similar)

    kept = []
    if Path(a.out).exists():
        old = json.loads(Path(a.out).read_text(encoding="utf-8"))
        played = (date.today() - date.fromisoformat(old["start"])).days + 1
        kept = old["ids"][:max(0, played)] if old["start"] == a.start else []

    ids = build(answers, tiers, difficulty, a.days, a.seed, kept)
    check(ids, answers, tiers)

    out = {
        "start": a.start, "seed": a.seed, "ids": ids,
        "players": {p["id"]: {"tier": tiers[p["id"]], "similar": similar[p["id"]], "difficulty": difficulty[p["id"]]}
                    for p in answers},
    }
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    page = Path(a.page)
    html, n = EMBED.subn(lambda m: m.group(1) + json.dumps({"start": a.start, "ids": ids}, separators=(",", ":")) + m.group(2),
                         page.read_text(encoding="utf-8"))
    if n != 1:
        raise SystemExit(f"calendar block not found in {page}")
    page.write_text(html, encoding="utf-8")
    last_day = date.fromisoformat(a.start) + timedelta(days=a.days - 1)
    print(f"wrote {a.out}: {len(ids)} days to {last_day}, {len(kept)} kept, {len(set(ids))} players used")


if __name__ == "__main__":
    main()
