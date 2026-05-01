from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .models import BookmakerOdds, DiscoveredMatch, TimingStatus
from .utils import normalize_bookmaker_name, parse_float

_EVENT_ID_RE = re.compile(r"/([A-Za-z0-9]{8})/$")


class OddsParser:
    def parse_available_markets(self, html: str) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        markets: list[str] = []
        for node in soup.select("[data-tab]"):
            market = str(node.get("data-tab", "")).strip().lower()
            if not market or market in markets:
                continue
            markets.append(market)
        return markets

    def parse_match_odds_payload(self, payload: str) -> list[BookmakerOdds]:
        data = json.loads(payload)
        odds_html = data.get("odds", "")
        return self.parse_match_odds_html(odds_html)

    def parse_match_odds_html(self, odds_html: str) -> list[BookmakerOdds]:
        soup = BeautifulSoup(odds_html, "lxml")
        rows: list[BookmakerOdds] = []

        for tr in soup.select("tr"):
            odd_cells = tr.select("td[data-odd]")
            if len(odd_cells) < 2:
                continue
            bookmaker = self._bookmaker_name(tr, odd_cells[0])
            if not bookmaker:
                continue
            normalized = normalize_bookmaker_name(bookmaker)
            values = [parse_float(cell.get("data-odd")) for cell in odd_cells[:3]]
            while len(values) < 3:
                values.append(None)
            rows.append(
                BookmakerOdds(
                    bookmaker=bookmaker,
                    normalized_bookmaker=normalized,
                    home_odds=values[0],
                    draw_odds=values[1],
                    away_odds=values[2],
                    bookmaker_id=self._clean_attr(tr.get("data-bid") or odd_cells[0].get("data-bookmaker-id")),
                    betexplorer_bookmaker_id=self._clean_attr(tr.get("data-bookie-id") or odd_cells[0].get("data-bookie-id")),
                    raw_row_text=tr.get_text(" ", strip=True),
                    raw_attributes=self._attrs(tr),
                )
            )
        return rows

    def _bookmaker_name(self, tr: Tag, first_odd_cell: Tag) -> str | None:
        explicit = first_odd_cell.get("data-bookie")
        if explicit:
            return explicit.strip()
        logo_link = tr.select_one("a.in-bookmaker-logo-link")
        if logo_link:
            text = logo_link.get_text(" ", strip=True)
            if text:
                return text
        title = tr.select_one("[title]")
        if title and title.get("title"):
            return title.get("title", "").strip()
        return None

    def _clean_attr(self, value: Any) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip().strip('"')
        return cleaned or None

    def _attrs(self, tr: Tag) -> dict[str, Any]:
        attrs = {key: value for key, value in tr.attrs.items() if isinstance(key, str)}
        line = tr.select_one(".table-main__doubleparameter")
        if line:
            text = line.get_text(" ", strip=True)
            if text:
                attrs["market_line"] = text
        return attrs


class DiscoveryParser:
    def __init__(self, base_url: str = "https://www.betexplorer.com", finish_grace_minutes: int = 120) -> None:
        self.base_url = base_url.rstrip("/")
        self.finish_grace_minutes = finish_grace_minutes

    def parse_homepage(self, html: str, now: datetime | None = None) -> list[DiscoveredMatch]:
        soup = BeautifulSoup(html, "lxml")
        matches: list[DiscoveredMatch] = []
        for li in soup.select("li[data-event-id]"):
            event_id = str(li.get("data-event-id", "")).strip()
            if not event_id:
                continue
            link = li.select_one('a[href*="/football/"][href$="/"]')
            href = link.get("href") if link else None
            if not href:
                continue
            match = _EVENT_ID_RE.search(href)
            if not match or match.group(1) != event_id:
                continue
            teams = self._teams(li)
            if len(teams) < 2:
                continue
            kickoff_time = self._kickoff_time(li)
            score = self._score(li)
            finished = self._looks_finished(kickoff_time, score, now)
            matches.append(
                DiscoveredMatch(
                    event_id=event_id,
                    source_url=urljoin(f"{self.base_url}/", href),
                    league=self._league(li),
                    home_team=teams[0],
                    away_team=teams[1],
                    kickoff_time=kickoff_time,
                    timing_status=TimingStatus.FINISHED if finished else TimingStatus.UNKNOWN,
                    status="finished" if finished else "scheduled",
                    live_score=score,
                )
            )
        for tr in soup.select("tr[data-dt]"):
            link = tr.select_one('a[href*="/football/"][href$="/"]')
            href = link.get("href") if link else None
            if not href:
                continue
            match = _EVENT_ID_RE.search(href)
            if not match:
                continue
            teams = self._teams(tr)
            if len(teams) < 2:
                continue
            kickoff_time = self._kickoff_time(tr)
            score = self._score(tr)
            finished = self._looks_finished(kickoff_time, score, now)
            matches.append(
                DiscoveredMatch(
                    event_id=match.group(1),
                    source_url=urljoin(f"{self.base_url}/", href),
                    league=self._league(tr),
                    home_team=teams[0],
                    away_team=teams[1],
                    kickoff_time=kickoff_time,
                    timing_status=TimingStatus.FINISHED if finished else TimingStatus.UNKNOWN,
                    status="finished" if finished else "scheduled",
                    live_score=score,
                )
            )
        return matches

    def apply_live_results(self, matches: list[DiscoveredMatch], payload: str) -> list[DiscoveredMatch]:
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return matches
        events = data.get("events", {})
        by_id = {match.event_id: match for match in matches}
        for event_id, event in events.items():
            match = by_id.get(event_id)
            if not match:
                continue
            match.status = "finished" if event.get("finished") == 1 else "live"
            match.live_score = event.get("score")
            match.timing_status = TimingStatus.FINISHED if event.get("finished") == 1 else TimingStatus.LIVE
        return matches

    def parse_match_page_result(self, html: str) -> tuple[bool, str | None]:
        soup = BeautifulSoup(html, "lxml")
        finished = False
        for script in soup.select('script[type="application/ld+json"]'):
            text = script.string or script.get_text("", strip=True)
            if '"eventStatus"' in text and "Finished" in text:
                finished = True
                break
        if not finished and re.search(r"\beventStatus\b[^<]{0,80}\bFinished\b", html, flags=re.I):
            finished = True

        score = None
        score_node = soup.select_one(".list-details__item__score")
        if score_node:
            score = self._score_from_text(score_node.get_text(" ", strip=True))
        if not score:
            details = soup.select_one(".list-details")
            if details:
                score = self._score_from_text(details.get_text(" ", strip=True))
        return finished, score

    def _teams(self, li: Tag) -> list[str]:
        text_nodes = []
        for selector in (".table-main__participantHome", ".table-main__participantAway", ".table-main__participant"):
            text_nodes.extend([node.get_text(" ", strip=True) for node in li.select(selector)])
        cleaned = [text for text in text_nodes if text and text not in {"-", ":"}]
        if len(cleaned) >= 2:
            return cleaned[:2]
        link = li.select_one('a[href*="/football/"]')
        if not link:
            return []
        text = re.sub(r"\s+", " ", link.get_text(" ", strip=True))
        parts = [part.strip() for part in re.split(r"\s+-\s+|\s+vs\s+", text, flags=re.I) if part.strip()]
        return parts[:2]

    def _league(self, li: Tag) -> str | None:
        tournament = li.find_previous("tr", class_=re.compile("js-tournament"))
        if tournament:
            link = tournament.select_one(".table-main__tournament")
            if link:
                return link.get_text(" ", strip=True)
        prev = li.find_previous("p", class_=re.compile("leaguesNames"))
        if prev:
            return prev.get_text(" ", strip=True)
        return None

    def _first_attr(self, li: Tag, attr: str) -> str | None:
        if li.get(attr):
            return str(li.get(attr))
        nested = li.select_one(f"[{attr}]")
        if nested:
            return str(nested.get(attr))
        return None

    def _kickoff_time(self, row: Tag) -> datetime | None:
        parsed = self._parse_betexplorer_datetime(self._first_attr(row, "data-dt"))
        if not parsed:
            return None
        displayed_time = self._displayed_time(row)
        if not displayed_time:
            return parsed
        hour, minute = displayed_time
        return parsed.replace(hour=hour, minute=minute)

    def _displayed_time(self, row: Tag) -> tuple[int, int] | None:
        time_node = row.select_one(".table-main__time, .table-main__matchHour")
        if not time_node:
            return None
        match = re.search(r"\b([0-2]?\d):([0-5]\d)\b", time_node.get_text(" ", strip=True))
        if not match:
            return None
        hour = int(match.group(1))
        minute = int(match.group(2))
        if hour > 23:
            return None
        return hour, minute

    def _score(self, row: Tag) -> str | None:
        for selector in (
            ".table-main__result",
            ".table-main__score",
            ".table-main__matchResult",
            ".table-main__partial",
            "[class*='score']",
            "[class*='result']",
        ):
            for node in row.select(selector):
                text = node.get_text(" ", strip=True)
                match = re.search(r"\b(\d{1,2})\s*[:\-]\s*(\d{1,2})\b", text)
                if match:
                    return f"{match.group(1)}:{match.group(2)}"
        return None

    def _score_from_text(self, text: str) -> str | None:
        match = re.search(r"\b(\d{1,2})\s*[:\-]\s*(\d{1,2})\b", text)
        if match:
            return f"{match.group(1)}:{match.group(2)}"
        return None

    def _looks_finished(self, kickoff_time: datetime | None, score: str | None, now: datetime | None) -> bool:
        if not score or not kickoff_time or not now:
            return False
        return kickoff_time <= now.replace(tzinfo=None) - timedelta(minutes=self.finish_grace_minutes)

    def _parse_betexplorer_datetime(self, value: str | None) -> datetime | None:
        if not value:
            return None
        parts = [int(part) for part in value.split(",") if part.strip().isdigit()]
        if len(parts) < 5:
            return None
        day, month, year, hour, minute = parts[:5]
        return datetime(year, month, day, hour, minute)
