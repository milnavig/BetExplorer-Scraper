from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import httpx


@dataclass(slots=True)
class RawResponse:
    url: str
    text: str
    status_code: int


class BetExplorerTransport:
    async def fetch_homepage(self) -> RawResponse:
        raise NotImplementedError

    async def fetch_football_date(self, target_date: date) -> RawResponse:
        raise NotImplementedError

    async def fetch_live_results(self) -> RawResponse:
        raise NotImplementedError

    async def fetch_match_page(self, match_url: str) -> RawResponse:
        raise NotImplementedError

    async def fetch_match_odds(self, event_id: str, referer_url: str, market: str = "1x2") -> RawResponse:
        raise NotImplementedError


class HttpBetExplorerTransport(BetExplorerTransport):
    def __init__(
        self,
        base_url: str = "https://www.betexplorer.com",
        timeout: float = 30.0,
        timezone_offset: str = "+3",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:150.0) Gecko/20100101 Firefox/150.0",
            "Accept-Language": "en-US,en;q=0.9",
        }
        if timezone_offset:
            self.headers["Cookie"] = f"my_timezone={timezone_offset}"

    async def fetch_homepage(self) -> RawResponse:
        return await self._get(f"{self.base_url}/", {"Accept": "text/html,*/*"})

    async def fetch_football_date(self, target_date: date) -> RawResponse:
        url = (
            f"{self.base_url}/football/results/"
            f"?year={target_date.year}&month={target_date.month:02d}&day={target_date.day:02d}"
        )
        return await self._get(url, {"Accept": "text/html,*/*"})

    async def fetch_live_results(self) -> RawResponse:
        return await self._get(
            f"{self.base_url}/gres/ajax/live-results.php?lang=en",
            {"Accept": "application/json, text/javascript, */*; q=0.01", "X-Requested-With": "XMLHttpRequest"},
        )

    async def fetch_match_page(self, match_url: str) -> RawResponse:
        return await self._get(match_url, {"Accept": "text/html,*/*"})

    async def fetch_match_odds(self, event_id: str, referer_url: str, market: str = "1x2") -> RawResponse:
        url = f"{self.base_url}/match-odds/{event_id}/0/{market}/bestOdds/?lang=en"
        return await self._get(
            url,
            {
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": referer_url,
            },
        )

    async def _get(self, url: str, headers: dict[str, str]) -> RawResponse:
        merged = {**self.headers, **headers}
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True, headers=merged) as client:
            response = await client.get(url)
            response.raise_for_status()
            return RawResponse(url=str(response.url), text=response.text, status_code=response.status_code)


class BrowserFallbackTransport(BetExplorerTransport):
    async def fetch_homepage(self) -> RawResponse:
        raise NotImplementedError("Browser fallback transport is reserved for a future Playwright implementation.")

    async def fetch_football_date(self, target_date: date) -> RawResponse:
        raise NotImplementedError("Browser fallback transport is reserved for a future Playwright implementation.")

    async def fetch_live_results(self) -> RawResponse:
        raise NotImplementedError("Browser fallback transport is reserved for a future Playwright implementation.")

    async def fetch_match_page(self, match_url: str) -> RawResponse:
        raise NotImplementedError("Browser fallback transport is reserved for a future Playwright implementation.")

    async def fetch_match_odds(self, event_id: str, referer_url: str, market: str = "1x2") -> RawResponse:
        raise NotImplementedError("Browser fallback transport is reserved for a future Playwright implementation.")
