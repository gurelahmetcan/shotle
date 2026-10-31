# Shotle

A daily NBA guessing game. Study the mystery player's zone-by-zone shot chart and find them in 6 guesses.

The site is a single file, `index.html`. Player data and the calendar are embedded in it, so there is no server or build step.

## Rebuilding the data

```bash
python3 -m venv .venv
.venv/bin/pip install nba_api pandas
.venv/bin/python shotle_data.py --season 2025-26
.venv/bin/python shotle_calendar.py
```

- `shotle_data.py` fetches `stats.nba.com`, writes `shotle-data.json` and embeds it into `index.html`. Raw responses are kept in `shotle_cache/`.
- `shotle_calendar.py` writes the daily player calendar to `puzzles.json` and embeds it into `index.html`. Days up to today are kept, future days can change when regenerated.

This project is not affiliated with the NBA. Data comes from the NBA's public stats pages.
