#!/usr/bin/env python3
"""Check the saved season file for gaps, contradictions and made-up shape.

This does not download anything. It only reads data/season.json.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "season.json"
LONDON = ZoneInfo("Europe/London")
BLUES = "Birmingham City"
SCORING = {"goal", "penalty", "own-goal"}


def fail(messages: list[str]) -> None:
    print("Season data failed these checks:", file=sys.stderr)
    for message in messages:
        print(f" - {message}", file=sys.stderr)
    sys.exit(1)


def blues_score(match: dict, side: str) -> int | None:
    if side == "for":
        return match["homeScore"] if match["bluesHome"] else match["awayScore"]
    return match["awayScore"] if match["bluesHome"] else match["homeScore"]


def main() -> int:
    problems: list[str] = []
    if not DATA_PATH.exists():
        fail(["data/season.json is missing."])
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))

    if data.get("club") != BLUES:
        problems.append("Club name is not Birmingham City.")
    if not str(data.get("season", "")).count("/") == 1:
        problems.append("Season label is missing.")
    sources = data.get("sources") or []
    if not sources or any(source.get("needsKey") for source in sources):
        problems.append("A listed source says it needs an API key. This site should run without one.")
    if "ESPN" not in " ".join(source.get("name", "") for source in sources):
        problems.append("ESPN is not listed as a source.")

    rows = (data.get("table") or {}).get("rows") or []
    if len(rows) != 24:
        problems.append(f"Championship table has {len(rows)} rows, expected 24.")
    blues_rows = [row for row in rows if row.get("isBlues")]
    if len(blues_rows) != 1:
        problems.append("Birmingham should appear once in the table.")
    for row in rows:
        played = row["won"] + row["drawn"] + row["lost"]
        if row["played"] != played:
            problems.append(f"{row['team']} played {row['played']} but W/D/L add up to {played}.")
        if row["goalDifference"] != row["goalsFor"] - row["goalsAgainst"]:
            problems.append(f"{row['team']} goal difference does not match the goals.")
        expected = row["won"] * 3 + row["drawn"] - row["deduction"]
        if row["points"] != expected:
            problems.append(
                f"{row['team']} has {row['points']} points; "
                f"wins, draws and the deduction add up to {expected}."
            )
        if row["deduction"] < 0 or row["points"] < 0:
            problems.append(f"{row['team']} has a negative points figure.")

    matches = data.get("matches") or []
    ids = [match["id"] for match in matches]
    if len(ids) != len(set(ids)):
        problems.append("Two matches share the same id.")
    championship = [match for match in matches if match["competitionCode"] == "championship"]
    # A Championship season is 46 games. Refuse a short list instead of
    # publishing a fixture list with holes in it.
    if len(championship) != 46:
        problems.append(f"Expected 46 Championship fixtures, found {len(championship)}.")
    cups = [match for match in matches if match["competitionCode"] == "carabao-cup"]
    if len(cups) < 2:
        problems.append("Carabao Cup ties are missing.")
    fa_cup = [match for match in matches if match["competitionCode"] == "fa-cup"]
    gaps = data.get("gaps") or []
    if not fa_cup and not any("FA Cup" in gap for gap in gaps):
        problems.append("FA Cup is empty but the page does not say so.")

    for match in matches:
        teams = {match.get("homeTeam"), match.get("awayTeam")}
        if BLUES not in teams:
            problems.append(f"Match {match.get('id')} does not include Birmingham City.")
        kickoff = datetime.fromisoformat(match["kickoffUtc"].replace("Z", "+00:00")).astimezone(LONDON)
        if kickoff.tzinfo is None:
            problems.append(f"Match {match.get('id')} kick-off has no timezone.")
        if match.get("timeKnown"):
            if match.get("timeUk") != kickoff.strftime("%H:%M"):
                problems.append(f"Match {match.get('id')} UK time does not match the kick-off.")
            if match.get("dateLong") != kickoff.strftime("%A %-d %B"):
                problems.append(f"Match {match.get('id')} date label does not match the kick-off.")
        status = match.get("status")
        if status in ("finished", "live"):
            if not isinstance(match.get("homeScore"), int) or not isinstance(match.get("awayScore"), int):
                problems.append(f"Match {match.get('id')} is {status} without a score.")
            elif match["homeScore"] < 0 or match["awayScore"] < 0:
                problems.append(f"Match {match.get('id')} has a negative score.")
        elif status in ("scheduled", "postponed"):
            if match.get("homeScore") is not None or match.get("awayScore") is not None:
                problems.append(f"Match {match.get('id')} has a score before it has been played.")
        if match.get("attendance") is not None and match["attendance"] <= 0:
            problems.append(f"Match {match.get('id')} has a zero attendance instead of a blank.")
        if status == "finished" and match.get("scorersComplete"):
            home_goals = sum(
                1
                for item in match.get("scorers") or []
                if item.get("team") == match["homeTeam"] and item.get("kind") in SCORING
            )
            away_goals = sum(
                1
                for item in match.get("scorers") or []
                if item.get("team") == match["awayTeam"] and item.get("kind") in SCORING
            )
            if home_goals != match["homeScore"] or away_goals != match["awayScore"]:
                problems.append(f"Scorers for match {match.get('id')} do not add up to the score.")
        if status == "finished" and not match.get("scorersComplete"):
            label = f"{match.get('homeTeam')} v {match.get('awayTeam')}"
            if not any(label in gap for gap in gaps):
                problems.append(f"{label} is missing scorers and the page does not say so.")
        if status == "finished" and not match.get("statsAvailable"):
            label = f"{match.get('homeTeam')} v {match.get('awayTeam')}"
            if not any(label in gap for gap in gaps):
                problems.append(f"{label} is missing stats and the page does not say so.")

    totals = data.get("seasonTotals") or {}
    recounted: dict[str, dict] = {}
    own_goals = 0
    for match in matches:
        if match.get("status") != "finished" or not match.get("scorersComplete"):
            continue
        for item in match.get("scorers") or []:
            if item.get("team") != BLUES:
                continue
            if item.get("kind") == "own-goal":
                own_goals += 1
                continue
            if item.get("kind") not in ("goal", "penalty") or not item.get("player"):
                continue
            row = recounted.setdefault(item["player"], {"goals": 0, "penalties": 0})
            row["goals"] += 1
            if item["kind"] == "penalty":
                row["penalties"] += 1
    listed = {row["player"]: row for row in totals.get("scorers") or []}
    if set(listed) != set(recounted):
        problems.append("Top scorers do not match the goals stored on the matches.")
    for player, row in recounted.items():
        shown = listed.get(player) or {}
        if shown.get("goals") != row["goals"] or shown.get("penalties") != row["penalties"]:
            problems.append(f"Top scorer total for {player} does not match the match list.")
    if len(totals.get("ownGoalsForBlues") or []) != own_goals:
        problems.append("Own-goal list does not match the matches.")

    if blues_rows:
        blues = blues_rows[0]
        league_for = 0
        league_against = 0
        for match in championship:
            if match.get("status") != "finished":
                continue
            scored = blues_score(match, "for")
            conceded = blues_score(match, "against")
            if isinstance(scored, int) and isinstance(conceded, int):
                league_for += scored
                league_against += conceded
        if league_for != blues["goalsFor"] or league_against != blues["goalsAgainst"]:
            problems.append(
                "Birmingham's goals in the Championship results do not match the table "
                f"({league_for}-{league_against} from results, "
                f"{blues['goalsFor']}-{blues['goalsAgainst']} in the table)."
            )

    if problems:
        fail(problems)
    print(
        f"Checked {len(matches)} matches and {len(rows)} table rows in {DATA_PATH.relative_to(ROOT)}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
