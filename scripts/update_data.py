#!/usr/bin/env python3
"""Refresh the saved Birmingham City 2026/27 data.

Reads the public ESPN football feed (no account and no API key) for
fixtures, kick-off times, scores, scorers, match stats and the
Championship table. Matchday numbers come from the public-domain
openfootball list when the date and both clubs match. Scores from
openfootball are never written onto the site; that file often lags.

If a download fails, the previous saved file is left as it is.
Nothing in this script invents a score, a fixture or a statistic.
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "season.json"
HISTORY_DIR = ROOT / "data" / "history"

BLUES_ID = "392"
BLUES_NAME = "Birmingham City"
LONDON = ZoneInfo("Europe/London")
USER_AGENT = (
    "BirminghamCityBluesTracker/1.0 "
    "(unofficial fan site; +https://github.com/Rich-33/Birmingham-City-Fc-tracker)"
)

COMPETITIONS = (
    {
        "slug": "eng.2",
        "code": "championship",
        "name": "Championship",
        "fullName": "EFL Championship",
    },
    {
        "slug": "eng.league_cup",
        "code": "carabao-cup",
        "name": "Carabao Cup",
        "fullName": "EFL Cup (Carabao Cup)",
    },
    {
        "slug": "eng.fa",
        "code": "fa-cup",
        "name": "FA Cup",
        "fullName": "FA Cup",
    },
)

STAT_KEYS = (
    "possessionPct",
    "totalShots",
    "shotsOnTarget",
    "wonCorners",
    "foulsCommitted",
    "offsides",
    "saves",
    "yellowCards",
    "redCards",
)

OPENFOOTBALL_URL = (
    "https://raw.githubusercontent.com/openfootball/football.json/"
    "master/{start}-{end}/en.2.json"
)


def season_start_year(now: datetime) -> int:
    """Football season that is underway on this London date."""
    return now.year if now.month >= 7 else now.year - 1


def season_label(start: int) -> str:
    return f"{start}/{(start + 1) % 100:02d}"


def fetch_json(url: str, retries: int = 4) -> dict:
    delay = 1.0
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=45) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            last_error = error
            if error.code not in (429, 500, 502, 503, 504):
                raise
        except Exception as error:  # noqa: BLE001 - keep the saved file on any network miss
            last_error = error
        if attempt < retries - 1:
            time.sleep(delay)
            delay *= 2
    raise RuntimeError(f"Could not download {url}: {last_error}")


def team_id_from_ref(team: dict) -> str | None:
    if not isinstance(team, dict):
        return None
    if team.get("id") and "$ref" not in team:
        return str(team["id"])
    ref = team.get("$ref") or ""
    match = re.search(r"/teams/(\d+)", ref)
    if match:
        return match.group(1)
    if team.get("id"):
        return str(team["id"])
    return None


def parse_attendance(value) -> int | None:
    """Zero usually means the feed left attendance blank, so keep it blank."""
    if value is None or value == "":
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def parse_score(value, status: str) -> int | None:
    if status not in ("finished", "live"):
        return None
    if isinstance(value, dict):
        value = value.get("displayValue", value.get("value"))
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def map_status(status_type: dict | None) -> str:
    name = ((status_type or {}).get("name") or "").upper()
    state = ((status_type or {}).get("state") or "").lower()
    if "POSTPON" in name:
        return "postponed"
    if "CANCEL" in name or "ABANDON" in name:
        return "called-off"
    if state == "in" or "HALF" in name or name in ("STATUS_IN_PROGRESS", "STATUS_LIVE"):
        return "live"
    if state == "post" or name in ("STATUS_FULL_TIME", "STATUS_FINAL"):
        return "finished"
    if state == "pre" or "SCHED" in name or name == "STATUS_PRE":
        return "scheduled"
    return "unknown"


def classify_event(type_text: str) -> str | None:
    text = type_text or ""
    if text.startswith("Own Goal"):
        return "own-goal"
    if text in ("Penalty - Scored", "Penalty - Goal"):
        return "penalty"
    if text in ("Penalty - Saved", "Penalty - Missed") or text.startswith("Penalty - Missed"):
        return "penalty-saved"
    if text.startswith("Goal"):
        return "goal"
    if text == "Yellow Card":
        return "yellow"
    if text in ("Red Card", "Second Yellow Card", "Yellow Red Card"):
        return "red"
    return None


def london_labels(kickoff: datetime) -> dict:
    local = kickoff.astimezone(LONDON)
    return {
        "kickoffUtc": kickoff.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "dateShort": local.strftime("%a %-d %b"),
        "dateLong": local.strftime("%A %-d %B"),
        "timeUk": local.strftime("%H:%M"),
        "londonDate": local.date().isoformat(),
    }


def norm_team(name: str) -> str:
    text = name.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9 ]", "", text)
    text = re.sub(r"\b(fc|afc)\b", "", text)
    return re.sub(r"\s+", " ", text).strip()


def load_existing() -> dict | None:
    if not DATA_PATH.exists():
        return None
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def fetch_standings() -> tuple[list[dict], dict[str, str]]:
    payload = fetch_json("https://site.api.espn.com/apis/v2/sports/soccer/eng.2/standings")
    children = payload.get("children") or []
    if not children:
        raise RuntimeError("Championship table was empty.")
    entries = children[0].get("standings", {}).get("entries") or []
    if len(entries) < 20:
        raise RuntimeError(f"Championship table only had {len(entries)} clubs.")
    rows = []
    names: dict[str, str] = {}
    for entry in entries:
        team = entry.get("team") or {}
        team_id = str(team.get("id"))
        stats = {item.get("name"): item for item in entry.get("stats") or []}

        def number(key: str) -> int:
            raw = stats.get(key) or {}
            value = raw.get("value")
            if value is None or value == "":
                display = raw.get("displayValue") or "0"
                display = str(display).replace("+", "")
                return int(display or 0)
            return int(value)

        name = team.get("displayName") or "Unknown club"
        names[team_id] = name
        rows.append(
            {
                "rank": number("rank"),
                "teamId": team_id,
                "team": name,
                "played": number("gamesPlayed"),
                "won": number("wins"),
                "drawn": number("ties"),
                "lost": number("losses"),
                "goalsFor": number("pointsFor"),
                "goalsAgainst": number("pointsAgainst"),
                "goalDifference": number("pointDifferential"),
                "points": number("points"),
                "deduction": number("deductions"),
                "isBlues": team_id == BLUES_ID or name == BLUES_NAME,
            }
        )
    rows.sort(key=lambda row: (row["rank"], row["team"]))
    return rows, names


def fetch_event_refs(slug: str, year: int) -> list[str]:
    url = (
        "https://sports.core.api.espn.com/v2/sports/soccer/leagues/"
        f"{slug}/seasons/{year}/teams/{BLUES_ID}/events?limit=100"
    )
    payload = fetch_json(url)
    refs = [item["$ref"] for item in payload.get("items") or [] if item.get("$ref")]
    if payload.get("pageCount", 1) > 1:
        raise RuntimeError(f"{slug} returned more than one page of fixtures.")
    return refs


def lookup_team_name(team_id: str, cache: dict[str, str]) -> str:
    if team_id in cache:
        return cache[team_id]
    payload = fetch_json(
        f"https://sports.core.api.espn.com/v2/sports/soccer/teams/{team_id}?lang=en&region=us"
    )
    name = payload.get("displayName") or payload.get("name")
    if not name:
        raise RuntimeError(f"No name for club id {team_id}.")
    cache[team_id] = name
    return name


def event_teams(event: dict, cache: dict[str, str]) -> list[dict]:
    competition = (event.get("competitions") or [{}])[0]
    sides = []
    for competitor in competition.get("competitors") or []:
        team_id = team_id_from_ref(competitor.get("team") or {})
        if not team_id:
            raise RuntimeError(f"Fixture {event.get('id')} is missing a club id.")
        home_away = competitor.get("homeAway")
        if home_away not in ("home", "away"):
            raise RuntimeError(f"Fixture {event.get('id')} has no home or away side.")
        sides.append(
            {
                "id": team_id,
                "name": lookup_team_name(team_id, cache),
                "homeAway": home_away,
                "score": (competitor.get("score") or {}).get("displayValue")
                if isinstance(competitor.get("score"), dict)
                else competitor.get("score"),
            }
        )
    return sides


def fixture_shell(event: dict, competition: dict, cache: dict[str, str]) -> dict:
    kickoff_raw = event.get("date")
    if not kickoff_raw:
        raise RuntimeError(f"Fixture {event.get('id')} has no kick-off.")
    kickoff = datetime.fromisoformat(kickoff_raw.replace("Z", "+00:00"))
    sides = event_teams(event, cache)
    home = next(side for side in sides if side["homeAway"] == "home")
    away = next(side for side in sides if side["homeAway"] == "away")
    if BLUES_ID not in (home["id"], away["id"]):
        raise RuntimeError(f"Fixture {event.get('id')} does not include Birmingham City.")
    venue = ((event.get("competitions") or [{}])[0].get("venue") or {}).get("fullName")
    competition_block = (event.get("competitions") or [{}])[0]
    labels = london_labels(kickoff)
    return {
        "id": str(event.get("id")),
        "competition": competition["name"],
        "competitionCode": competition["code"],
        "round": None,
        "timeKnown": bool(event.get("timeValid", True)),
        "status": "scheduled",
        "statusDetail": None,
        "venue": venue or None,
        "attendance": parse_attendance(competition_block.get("attendance")),
        "homeTeam": home["name"],
        "awayTeam": away["name"],
        "homeId": home["id"],
        "awayId": away["id"],
        "bluesHome": home["id"] == BLUES_ID,
        "homeScore": None,
        "awayScore": None,
        "scorers": [],
        "cards": [],
        "scorersComplete": False,
        "stats": None,
        "statsAvailable": False,
        "reportUrl": f"https://www.espn.com/soccer/match/_/gameId/{event.get('id')}",
        "boxscoreAvailable": bool(competition_block.get("boxscoreAvailable")),
        **labels,
    }


def player_name(participant: dict) -> str | None:
    athlete = (participant or {}).get("athlete") or {}
    return athlete.get("displayName") or None


def parse_summary(summary: dict, shell: dict) -> dict:
    header = summary.get("header") or {}
    competition = (header.get("competitions") or [{}])[0]
    status_type = (competition.get("status") or {}).get("type") or {}
    status = map_status(status_type)
    match = dict(shell)
    match["status"] = status
    match["statusDetail"] = status_type.get("shortDetail") or status_type.get("detail")
    if competition.get("date"):
        kickoff = datetime.fromisoformat(competition["date"].replace("Z", "+00:00"))
        match.update(london_labels(kickoff))

    by_side = {}
    for competitor in competition.get("competitors") or []:
        side = competitor.get("homeAway")
        team = competitor.get("team") or {}
        by_side[side] = {
            "name": team.get("displayName"),
            "score": competitor.get("score"),
        }
    if by_side.get("home", {}).get("name"):
        match["homeTeam"] = by_side["home"]["name"]
    if by_side.get("away", {}).get("name"):
        match["awayTeam"] = by_side["away"]["name"]
    match["homeScore"] = parse_score(by_side.get("home", {}).get("score"), status)
    match["awayScore"] = parse_score(by_side.get("away", {}).get("score"), status)
    match["bluesHome"] = match["homeTeam"] == BLUES_NAME

    game_info = summary.get("gameInfo") or {}
    venue = (game_info.get("venue") or {}).get("fullName")
    if venue:
        match["venue"] = venue
    attendance = parse_attendance(game_info.get("attendance"))
    if attendance is not None:
        match["attendance"] = attendance

    note = competition.get("altGameNote") or ""
    if match["competitionCode"] != "championship" and "," in note:
        match["round"] = note.split(",", 1)[1].strip() or None

    scorers = []
    cards = []
    for event in summary.get("keyEvents") or []:
        type_text = (event.get("type") or {}).get("text") or ""
        kind = classify_event(type_text)
        if not kind:
            continue
        participants = event.get("participants") or []
        names = [player_name(person) for person in participants]
        names = [name for name in names if name]
        minute = (event.get("clock") or {}).get("displayValue")
        team = (event.get("team") or {}).get("displayName")
        sentence = event.get("text") or ""
        if kind in ("goal", "penalty", "own-goal"):
            own_club = None
            player = names[0] if names else None
            if kind == "own-goal":
                found = re.match(r"Own Goal by (.+?), ([^.]+)\.", sentence)
                if found:
                    player = player or found.group(1).strip()
                    own_club = found.group(2).strip()
            scorers.append(
                {
                    "team": team,
                    "player": player,
                    "minute": minute,
                    "kind": kind,
                    "assist": names[1] if kind != "own-goal" and len(names) > 1 else None,
                    "ownGoalByClub": own_club,
                    "text": sentence,
                }
            )
        elif kind == "penalty-saved":
            scorers.append(
                {
                    "team": team,
                    "player": names[0] if names else None,
                    "minute": minute,
                    "kind": kind,
                    "assist": None,
                    "ownGoalByClub": None,
                    "text": sentence,
                }
            )
        elif kind in ("yellow", "red"):
            detail = None
            if kind == "red" and "second yellow" in sentence.lower():
                detail = "Second yellow"
            cards.append(
                {
                    "team": team,
                    "player": names[0] if names else None,
                    "minute": minute,
                    "kind": kind,
                    "detail": detail,
                }
            )

    match["scorers"] = scorers
    match["cards"] = cards
    match["scorersComplete"] = scorers_add_up(match)

    stats_block = {}
    for side in (summary.get("boxscore") or {}).get("teams") or []:
        team_name = (side.get("team") or {}).get("displayName")
        values = {}
        for item in side.get("statistics") or []:
            if item.get("name") in STAT_KEYS and item.get("displayValue") not in (None, ""):
                values[item["name"]] = str(item["displayValue"])
        if team_name == match["homeTeam"]:
            stats_block["home"] = values
        elif team_name == match["awayTeam"]:
            stats_block["away"] = values
    if stats_block.get("home") or stats_block.get("away"):
        match["stats"] = {
            "home": stats_block.get("home") or {},
            "away": stats_block.get("away") or {},
        }
        match["statsAvailable"] = True
    else:
        match["stats"] = None
        match["statsAvailable"] = False
    return match


def scoring_kinds(kind: str) -> bool:
    return kind in ("goal", "penalty", "own-goal")


def scorers_add_up(match: dict) -> bool:
    if match["status"] != "finished":
        return False
    if match["homeScore"] is None or match["awayScore"] is None:
        return False
    home = sum(
        1
        for item in match["scorers"]
        if item.get("team") == match["homeTeam"] and scoring_kinds(item.get("kind"))
    )
    away = sum(
        1
        for item in match["scorers"]
        if item.get("team") == match["awayTeam"] and scoring_kinds(item.get("kind"))
    )
    return home == match["homeScore"] and away == match["awayScore"]


def fetch_summary(slug: str, event_id: str) -> dict:
    url = (
        "https://site.web.api.espn.com/apis/site/v2/sports/soccer/"
        f"{slug}/summary?event={event_id}"
    )
    return fetch_json(url)


def needs_report(shell: dict, now: datetime) -> bool:
    """Download a match report only once the game has kicked off.

    Future fixtures already include the date, teams and venue. Their
    boxscore flag is not reliable, so it is not used as a reason to
    download a report early.
    """
    kickoff = datetime.fromisoformat(shell["kickoffUtc"].replace("Z", "+00:00"))
    return kickoff <= now + timedelta(minutes=20)


def load_matchdays(start: int) -> tuple[dict, list[str]]:
    """Return matchday labels and kick-off times keyed by London date and clubs.

    Scores are read only so they can be compared. They are not copied in.
    """
    end = (start + 1) % 100
    url = OPENFOOTBALL_URL.format(start=start, end=f"{end:02d}")
    try:
        payload = fetch_json(url)
    except Exception as error:  # noqa: BLE001
        return {}, [f"Matchday numbers could not be loaded ({error})."]
    found = {}
    for match in payload.get("matches") or []:
        home = match.get("team1") or ""
        away = match.get("team2") or ""
        if "Birmingham" not in home and "Birmingham" not in away:
            continue
        date = match.get("date")
        if not date:
            continue
        key = (date, norm_team(home), norm_team(away))
        score = match.get("score")
        full_time = None
        if isinstance(score, list) and len(score) == 2:
            full_time = (score[0], score[1])
        elif isinstance(score, dict) and isinstance(score.get("ft"), list) and len(score["ft"]) == 2:
            full_time = (score["ft"][0], score["ft"][1])
        found[key] = {
            "round": match.get("round"),
            "time": match.get("time"),
            "fullTime": full_time,
        }
    return found, []


def apply_matchdays(matches: list[dict], matchdays: dict) -> list[dict]:
    warnings = []
    for match in matches:
        if match["competitionCode"] != "championship":
            continue
        key = (match["londonDate"], norm_team(match["homeTeam"]), norm_team(match["awayTeam"]))
        extra = matchdays.get(key)
        if not extra:
            warnings.append(
                f"No matchday number for {match['dateLong']}: "
                f"{match['homeTeam']} v {match['awayTeam']}."
            )
            continue
        if extra.get("round"):
            match["round"] = extra["round"]
        other_time = extra.get("time")
        if other_time and match.get("timeKnown") and other_time != match["timeUk"]:
            # Printed for the job log only. Televised games are often moved
            # after the original list was published, and the page keeps the
            # ESPN kick-off, which is the one refreshed each run.
            print(
                f"  Note: openfootball lists {other_time} for "
                f"{match['homeTeam']} v {match['awayTeam']} on {match['dateLong']}; "
                f"ESPN lists {match['timeUk']}. Using the ESPN time."
            )
        other_score = extra.get("fullTime")
        if (
            other_score
            and match["status"] == "finished"
            and match["homeScore"] is not None
            and (match["homeScore"], match["awayScore"]) != tuple(other_score)
        ):
            warnings.append(
                f"Score disagreement for {match['homeTeam']} v {match['awayTeam']} "
                f"on {match['dateLong']}: openfootball says {other_score[0]}-{other_score[1]}, "
                f"ESPN says {match['homeScore']}-{match['awayScore']}. "
                "This page shows the ESPN score."
            )
    return warnings


def merge_match(old: dict | None, new: dict) -> dict:
    if not old:
        return new
    if new["status"] in ("finished", "live") and new["homeScore"] is None and old.get("homeScore") is not None:
        new["homeScore"] = old["homeScore"]
        new["awayScore"] = old["awayScore"]
        if old.get("status") == "finished":
            new["status"] = "finished"
            new["statusDetail"] = old.get("statusDetail")
    same_score = (
        new.get("homeScore") == old.get("homeScore") and new.get("awayScore") == old.get("awayScore")
    )
    if same_score and new["status"] in ("finished", "live"):
        if not new.get("scorers") and old.get("scorers"):
            new["scorers"] = old["scorers"]
            new["scorersComplete"] = old.get("scorersComplete", False)
        if not new.get("statsAvailable") and old.get("statsAvailable"):
            new["stats"] = old["stats"]
            new["statsAvailable"] = True
        if not new.get("cards") and old.get("cards"):
            new["cards"] = old["cards"]
        if new.get("attendance") is None and old.get("attendance"):
            new["attendance"] = old["attendance"]
        if not new.get("round") and old.get("round"):
            new["round"] = old["round"]
    return new


def merge_matches(old_matches: list[dict], new_matches: list[dict]) -> list[dict]:
    old_by_id = {match["id"]: match for match in old_matches}
    new_ids = {match["id"] for match in new_matches}
    merged = [merge_match(old_by_id.get(match["id"]), match) for match in new_matches]
    for match in old_matches:
        # Keep a result that the feed no longer lists, so the record is not lost.
        if match["id"] not in new_ids and match.get("status") == "finished":
            merged.append(match)
    merged.sort(key=lambda match: match["kickoffUtc"])
    return merged


def season_totals(matches: list[dict]) -> dict:
    goals: dict[str, dict] = {}
    cards: dict[str, dict] = {}
    own_goals = []
    for match in matches:
        if match.get("status") != "finished" or not match.get("scorersComplete"):
            continue
        for item in match.get("scorers") or []:
            if item.get("team") != BLUES_NAME:
                continue
            if item.get("kind") == "own-goal":
                own_goals.append(
                    {
                        "player": item.get("player"),
                        "club": item.get("ownGoalByClub"),
                        "minute": item.get("minute"),
                        "opponent": match["awayTeam"] if match["bluesHome"] else match["homeTeam"],
                        "matchId": match["id"],
                        "dateShort": match["dateShort"],
                        "competition": match["competition"],
                    }
                )
                continue
            if item.get("kind") not in ("goal", "penalty"):
                continue
            player = item.get("player")
            if not player:
                continue
            row = goals.setdefault(
                player,
                {"player": player, "goals": 0, "penalties": 0, "byCompetition": {}},
            )
            row["goals"] += 1
            if item["kind"] == "penalty":
                row["penalties"] += 1
            row["byCompetition"][match["competition"]] = row["byCompetition"].get(match["competition"], 0) + 1
        for card in match.get("cards") or []:
            if card.get("team") != BLUES_NAME or not card.get("player"):
                continue
            row = cards.setdefault(card["player"], {"player": card["player"], "yellow": 0, "red": 0})
            if card.get("kind") == "yellow":
                row["yellow"] += 1
            elif card.get("kind") == "red":
                row["red"] += 1
    scorer_rows = sorted(goals.values(), key=lambda row: (-row["goals"], row["player"]))
    card_rows = sorted(cards.values(), key=lambda row: (-row["yellow"], -row["red"], row["player"]))
    return {"scorers": scorer_rows, "ownGoalsForBlues": own_goals, "cards": card_rows}


def competition_notes(matches: list[dict]) -> list[dict]:
    notes = []
    for competition in COMPETITIONS:
        mine = [match for match in matches if match["competitionCode"] == competition["code"]]
        upcoming = [match for match in mine if match["status"] in ("scheduled", "live", "postponed")]
        note = None
        if competition["code"] == "fa-cup" and not mine:
            note = "No 2026/27 FA Cup tie for Birmingham has been published yet."
        elif competition["code"] == "carabao-cup" and mine and not upcoming:
            note = "No further Carabao Cup tie is listed."
        elif competition["code"] == "championship" and len(mine) < 46:
            note = "The Championship fixture list from the source looks shorter than a full season."
        notes.append(
            {
                "code": competition["code"],
                "name": competition["name"],
                "fullName": competition["fullName"],
                "listed": len(mine),
                "upcoming": len(upcoming),
                "note": note,
            }
        )
    return notes


def build_gaps(matches: list[dict], matchday_gaps: list[str]) -> list[str]:
    gaps = list(matchday_gaps)
    fa_cup = [match for match in matches if match["competitionCode"] == "fa-cup"]
    if not fa_cup:
        gaps.append("FA Cup: no Birmingham City fixture has been published for 2026/27 yet.")
    missing_attendance = [
        match
        for match in matches
        if match["status"] == "finished" and match.get("attendance") is None
    ]
    if missing_attendance:
        gaps.append(
            "Attendance was not published for "
            + str(len(missing_attendance))
            + " finished "
            + ("match." if len(missing_attendance) == 1 else "matches.")
            + " Those rows leave it blank."
        )
    incomplete = [
        match
        for match in matches
        if match["status"] == "finished" and not match.get("scorersComplete")
    ]
    for match in incomplete:
        gaps.append(
            f"Scorers for {match['homeTeam']} v {match['awayTeam']} on {match['dateLong']} "
            "did not add up to the score, so that match is left out of the top-scorer list."
        )
    missing_stats = [
        match
        for match in matches
        if match["status"] == "finished" and not match.get("statsAvailable")
    ]
    for match in missing_stats:
        gaps.append(
            f"Team stats were not published for {match['homeTeam']} v {match['awayTeam']} "
            f"on {match['dateLong']}."
        )
    return gaps


def strip_internal(match: dict) -> dict:
    cleaned = dict(match)
    cleaned.pop("boxscoreAvailable", None)
    cleaned.pop("londonDate", None)
    cleaned.pop("homeId", None)
    cleaned.pop("awayId", None)
    if not cleaned.get("timeKnown"):
        cleaned["timeUk"] = None
    return cleaned


def document_body(matches: list[dict], table: list[dict], warnings: list[str], gaps: list[str], start: int) -> dict:
    return {
        "club": BLUES_NAME,
        "nickname": "Blues",
        "season": season_label(start),
        "seasonStartYear": start,
        "sources": [
            {
                "name": "ESPN public football feed",
                "needsKey": False,
                "usedFor": "Fixtures, UK kick-off times, results, scorers, match stats and the Championship table",
            },
            {
                "name": "openfootball football.json",
                "needsKey": False,
                "usedFor": "Championship matchday numbers only. Scores from that file are not used.",
            },
        ],
        "warnings": warnings,
        "gaps": gaps,
        "competitions": competition_notes(matches),
        "table": {"name": "Championship", "rows": table},
        "matches": [strip_internal(match) for match in matches],
        "seasonTotals": season_totals(matches),
    }


def semantically_equal(left: dict, right: dict) -> bool:
    def slim(payload: dict) -> dict:
        copy = json.loads(json.dumps(payload))
        copy.pop("updatedAt", None)
        copy.pop("updatedLabel", None)
        return copy

    return slim(left) == slim(right)


def archive_previous(existing: dict) -> None:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    label = str(existing.get("season") or "unknown").replace("/", "-")
    target = HISTORY_DIR / f"{label}.json"
    if not target.exists():
        target.write_text(json.dumps(existing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Archived the previous season to {target.relative_to(ROOT)}")


def build(now: datetime) -> dict:
    start = season_start_year(now)
    print(f"Building {season_label(start)} from the public ESPN feed...")
    table, names = fetch_standings()
    names[BLUES_ID] = BLUES_NAME
    matchdays, matchday_gaps = load_matchdays(start)
    shells = []
    for competition in COMPETITIONS:
        refs = fetch_event_refs(competition["slug"], start)
        print(f"  {competition['name']}: {len(refs)} fixtures listed")
        if competition["code"] == "championship" and len(refs) < 40:
            raise RuntimeError(
                f"Championship list only had {len(refs)} fixtures. Keeping the saved file."
            )
        events = []
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {pool.submit(fetch_json, ref): ref for ref in refs}
            for future in as_completed(futures):
                events.append(future.result())
        for event in events:
            shell = fixture_shell(event, competition, names)
            shell["_slug"] = competition["slug"]
            shells.append(shell)

    reports = [shell for shell in shells if needs_report(shell, now)]
    print(f"  Fetching match reports for {len(reports)} games...")

    def load_report(shell: dict) -> dict:
        summary = fetch_summary(shell["_slug"], shell["id"])
        return parse_summary(summary, shell)

    finished_by_id = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(load_report, shell): shell["id"] for shell in reports}
        for future in as_completed(futures):
            match = future.result()
            finished_by_id[match["id"]] = match

    matches = []
    for shell in shells:
        match = finished_by_id.get(shell["id"], shell)
        match.pop("_slug", None)
        matches.append(match)
    matches.sort(key=lambda match: match["kickoffUtc"])
    warnings = apply_matchdays(matches, matchdays)
    gaps = build_gaps(matches, matchday_gaps)
    return document_body(matches, table, warnings, gaps, start)


def write_document(payload: dict, now: datetime) -> None:
    payload = dict(payload)
    payload["updatedAt"] = now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload["updatedLabel"] = now.astimezone(LONDON).strftime("%A %-d %B %Y, %H:%M UK")
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def print_summary(payload: dict) -> None:
    blues = next((row for row in payload["table"]["rows"] if row["isBlues"]), None)
    if blues:
        print(
            f"Table: {blues['rank']}th, {blues['points']} pts, "
            f"goal difference {blues['goalDifference']:+d}."
        )
    upcoming = [match for match in payload["matches"] if match["status"] == "scheduled"]
    if upcoming:
        nxt = upcoming[0]
        opponent = nxt["awayTeam"] if nxt["bluesHome"] else nxt["homeTeam"]
        where = "home" if nxt["bluesHome"] else "away"
        print(f"Next: {nxt['dateLong']} {nxt['timeUk'] or 'time TBC'} UK, {opponent} ({where}).")
    scorers = payload["seasonTotals"]["scorers"]
    if scorers:
        top = scorers[0]
        print(f"Top scorer: {top['player']} {top['goals']}.")
    else:
        print("Top scorer: none yet.")
    if payload["warnings"]:
        print("Warnings:")
        for warning in payload["warnings"]:
            print(" -", warning)
    if payload["gaps"]:
        print("Gaps:")
        for gap in payload["gaps"]:
            print(" -", gap)


def main() -> int:
    now = datetime.now(LONDON)
    existing = load_existing()
    try:
        fresh = build(now)
    except Exception as error:  # noqa: BLE001
        print(f"Update failed: {error}", file=sys.stderr)
        if existing:
            print("The saved data has been left unchanged.", file=sys.stderr)
        return 1

    if existing and existing.get("season") and existing.get("season") != fresh["season"]:
        archive_previous(existing)
        merged_matches_source = []
    else:
        merged_matches_source = (existing or {}).get("matches") or []

    # Re-merge using the pre-strip matches is unnecessary: strip only drops
    # internal keys. Rebuild totals from the merged public records.
    if merged_matches_source:
        matchday_gaps = [
            gap
            for gap in fresh["gaps"]
            if gap.startswith("Matchday numbers") or gap.startswith("No matchday")
        ]
        fresh["matches"] = merge_matches(merged_matches_source, fresh["matches"])
        fresh["seasonTotals"] = season_totals(fresh["matches"])
        fresh["competitions"] = competition_notes(fresh["matches"])
        fresh["gaps"] = build_gaps(fresh["matches"], matchday_gaps)

    if existing and existing.get("season") == fresh["season"] and semantically_equal(existing, fresh):
        print("No change in fixtures, results, stats or the table.")
        print_summary(existing)
        return 0

    write_document(fresh, now)
    written = load_existing()
    print(f"Wrote {DATA_PATH.relative_to(ROOT)}")
    print_summary(written)
    return 0


if __name__ == "__main__":
    sys.exit(main())
