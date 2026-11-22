"""Client for Skylight Calendar's private app API.

Skylight publishes no API. This talks to the same endpoints the Skylight mobile
app uses, as documented by community projects (skycli, skylight-mcp,
pyskylight). It can stop working whenever Skylight changes their app, so
everything that uses it must fail soft.

Login is OAuth2 authorization-code + PKCE behind a web sign-in form, and
Skylight may ask for a 6-digit code it emails to the account owner.
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Callable
import hashlib
import logging
import re
import secrets
import time
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse
import uuid

import aiohttp

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://app.ourskylight.com"
CLIENT_ID = "skylight-mobile"
REDIRECT_URI = "https://ourskylight.com/welcome"
SCOPE = "everything"
API_VERSION = "2026-08-05"
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)
API_UA = "ha-shipshape"
TIMEOUT = aiohttp.ClientTimeout(total=30)

_TOKEN_RE = (
    re.compile(r'name="authenticity_token"[^>]*value="([^"]+)"'),
    re.compile(r'value="([^"]+)"[^>]*name="authenticity_token"'),
    re.compile(r'name="csrf-token"[^>]*content="([^"]+)"'),
    re.compile(r'content="([^"]+)"[^>]*name="csrf-token"'),
)


class SkylightError(Exception):
    """Any Skylight failure."""


class SkylightAuthError(SkylightError):
    """Credentials or tokens were rejected."""


class SkylightRateLimited(SkylightError):
    """Skylight asked us to slow down."""


def _scrape_token(html: str) -> str:
    for pattern in _TOKEN_RE:
        match = pattern.search(html)
        if match:
            return match.group(1)
    raise SkylightError("Skylight's sign-in page has changed (no form token found)")


class SkylightLogin:
    """Interactive sign-in. Needs its own session with a cookie jar."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session
        self._csrf: str | None = None
        self._fingerprint = str(uuid.uuid4())

    async def _get(self, url: str) -> tuple[int, str, str]:
        async with self._session.get(
            url,
            headers={"User-Agent": BROWSER_UA, "Accept": "text/html"},
            allow_redirects=True,
            timeout=TIMEOUT,
        ) as resp:
            return resp.status, str(resp.url), await resp.text()

    async def _post_form(self, path: str, data: dict[str, str], referer: str) -> str:
        async with self._session.post(
            f"{BASE_URL}{path}",
            data=data,
            headers={
                "User-Agent": BROWSER_UA,
                "Accept": "text/html",
                "Origin": BASE_URL,
                "Referer": f"{BASE_URL}{referer}",
            },
            allow_redirects=False,
            timeout=TIMEOUT,
        ) as resp:
            if resp.status == 429:
                raise SkylightRateLimited("Skylight is rate limiting sign-ins; try again later")
            if resp.status not in (301, 302, 303):
                raise SkylightAuthError(f"Unexpected sign-in response ({resp.status})")
            return resp.headers.get("Location", "")

    async def start(self, email: str, password: str) -> str:
        """Submit email and password. Returns 'ok' or 'mfa'."""
        _status, _url, html = await self._get(f"{BASE_URL}/auth/session/new")
        token = _scrape_token(html)
        location = await self._post_form(
            "/auth/session",
            {"authenticity_token": token, "email": email, "password": password},
            "/auth/session/new",
        )
        if "/auth/session/success" in location:
            return "ok"
        if "/auth/mfa_challenge" in location:
            _status, _url, html = await self._get(urljoin(BASE_URL, location))
            self._csrf = _scrape_token(html)
            return "mfa"
        raise SkylightAuthError("Skylight rejected that email or password")

    async def submit_code(self, code: str) -> str:
        """Submit the emailed 6-digit code. Returns 'ok'."""
        if self._csrf is None:
            raise SkylightError("No verification is in progress")
        location = await self._post_form(
            "/auth/mfa_challenge",
            {"authenticity_token": self._csrf, "code": code.strip()},
            "/auth/mfa_challenge/new",
        )
        if "/auth/session/success" in location:
            return "ok"
        # Wrong code: fetch a fresh form token so the user can try again.
        try:
            _status, _url, html = await self._get(f"{BASE_URL}/auth/mfa_challenge/new")
            self._csrf = _scrape_token(html)
        except SkylightError:
            pass
        raise SkylightAuthError("That code was not accepted")

    async def finish(self) -> dict[str, Any]:
        """Exchange the signed-in web session for API tokens."""
        verifier = secrets.token_urlsafe(64)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        )
        async with self._session.get(
            f"{BASE_URL}/oauth/authorize",
            params={
                "client_id": CLIENT_ID,
                "response_type": "code",
                "scope": SCOPE,
                "redirect_uri": REDIRECT_URI,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
            headers={"User-Agent": BROWSER_UA, "Accept": "text/html"},
            allow_redirects=False,
            timeout=TIMEOUT,
        ) as resp:
            location = resp.headers.get("Location", "")
        code = (parse_qs(urlparse(location).query).get("code") or [None])[0]
        if not code:
            raise SkylightAuthError("Skylight did not authorize the app session")
        async with self._session.post(
            f"{BASE_URL}/oauth/token",
            data={
                "grant_type": "authorization_code",
                "client_id": CLIENT_ID,
                "scope": SCOPE,
                "redirect_uri": REDIRECT_URI,
                "code": code,
                "code_verifier": verifier,
                "skylight_api_client_device_fingerprint": self._fingerprint,
                "skylight_api_client_device_platform": "web",
                "skylight_api_client_device_name": "unknown",
                "skylight_api_client_device_os_version": "10.15.7",
                "skylight_api_client_device_app_version": "unknown",
                "skylight_api_client_device_hardware": "Macintosh",
                "source": "js-mobile",
            },
            headers={"User-Agent": API_UA, "Accept": "application/json"},
            timeout=TIMEOUT,
        ) as resp:
            if resp.status != 200:
                raise SkylightAuthError(f"Skylight token exchange failed ({resp.status})")
            payload = await resp.json(content_type=None)
        return _tokens_from(payload, self._fingerprint)


def _tokens_from(payload: dict[str, Any], fingerprint: str) -> dict[str, Any]:
    if not payload.get("access_token"):
        raise SkylightAuthError("Skylight returned no access token")
    return {
        "access_token": payload["access_token"],
        "refresh_token": payload.get("refresh_token"),
        "expires_at": time.time() + float(payload.get("expires_in") or 86400),
        "fingerprint": fingerprint,
    }


class SkylightClient:
    """Authenticated API calls."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        tokens: dict[str, Any],
        on_tokens: Callable[[dict[str, Any]], None],
    ) -> None:
        self._session = session
        self._tokens = dict(tokens)
        self._on_tokens = on_tokens
        self._refresh_lock = asyncio.Lock()

    async def _refresh(self) -> None:
        async with self._refresh_lock:
            if self._tokens.get("expires_at", 0) - time.time() > 600:
                return  # another call already refreshed
            refresh = self._tokens.get("refresh_token")
            if not refresh:
                raise SkylightAuthError("Skylight sign-in expired; sign in again")
            async with self._session.post(
                f"{BASE_URL}/oauth/token",
                data={
                    "grant_type": "refresh_token",
                    "client_id": CLIENT_ID,
                    "refresh_token": refresh,
                    "skylight_api_client_device_fingerprint": self._tokens.get("fingerprint", ""),
                },
                headers={"User-Agent": API_UA, "Accept": "application/json"},
                timeout=TIMEOUT,
            ) as resp:
                if resp.status in (400, 401, 403):
                    raise SkylightAuthError("Skylight sign-in expired; sign in again")
                if resp.status != 200:
                    raise SkylightError(f"Skylight token refresh failed ({resp.status})")
                payload = await resp.json(content_type=None)
            self._tokens = _tokens_from(payload, self._tokens.get("fingerprint", ""))
            # Refresh tokens are single-use: persist the new pair immediately.
            self._on_tokens(dict(self._tokens))

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        _retry: bool = True,
    ) -> Any:
        if self._tokens.get("expires_at", 0) - time.time() < 300:
            await self._refresh()
        headers = {
            "Authorization": f"Bearer {self._tokens['access_token']}",
            "skylight-api-version": API_VERSION,
            "Accept": "application/json",
            "User-Agent": API_UA,
        }
        async with self._session.request(
            method, f"{BASE_URL}/api{path}", params=params, json=body, headers=headers, timeout=TIMEOUT
        ) as resp:
            if resp.status == 401 and _retry:
                self._tokens["expires_at"] = 0
                await self._refresh()
                return await self._request(method, path, params, body, _retry=False)
            if resp.status == 401:
                raise SkylightAuthError("Skylight rejected the saved sign-in")
            if resp.status == 429:
                raise SkylightRateLimited("Skylight rate limit reached")
            text = await resp.text()
            if resp.status >= 400:
                raise SkylightError(f"Skylight {method} {path} failed ({resp.status}): {text[:200]}")
            if not text.strip():
                return None
            try:
                return await resp.json(content_type=None)
            except ValueError as err:
                raise SkylightError(f"Skylight returned something unexpected for {path}") from err

    async def request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        """Raw API call, for diagnostics."""
        return await self._request(method.upper(), path, params, body)

    # --- reads -----------------------------------------------------------
    async def frames(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/frames")
        return [
            {
                "id": str(item["id"]),
                "name": (item.get("attributes") or {}).get("name")
                or (item.get("attributes") or {}).get("household_name")
                or str(item["id"]),
                "timezone": (item.get("attributes") or {}).get("timezone"),
            }
            for item in (data or {}).get("data", [])
        ]

    async def categories(self, frame: str) -> list[dict[str, Any]]:
        data = await self._request("GET", f"/frames/{frame}/categories")
        out = []
        for item in (data or {}).get("data", []):
            attrs = item.get("attributes") or {}
            out.append(
                {
                    "id": str(item["id"]),
                    "label": attrs.get("label") or str(item["id"]),
                    "person": bool(attrs.get("linked_to_profile")),
                }
            )
        return out

    async def chores(self, frame: str, after: str, before: str) -> list[dict[str, Any]]:
        data = await self._request(
            "GET",
            f"/frames/{frame}/chores",
            params={
                "after": after,
                "before": before,
                "include_late": "true",
                "include_up_for_grabs": "true",
            },
        )
        out = []
        for item in (data or {}).get("data", []):
            attrs = item.get("attributes") or {}
            out.append(
                {
                    "id": str(item["id"]),
                    "summary": attrs.get("summary"),
                    "status": attrs.get("status"),
                    "start": attrs.get("start"),
                    "up_for_grabs": bool(attrs.get("up_for_grabs")),
                    "reward_points": attrs.get("reward_points"),
                    "category_id": _rel_id(item, "category"),
                    "completed_category_id": _rel_id(item, "completed_category"),
                }
            )
        return out

    async def lists(self, frame: str) -> list[dict[str, Any]]:
        """Every list on the frame with its items."""
        data = await self._request("GET", f"/frames/{frame}/lists")
        items: dict[str, dict[str, Any]] = {}
        for inc in (data or {}).get("included") or []:
            if inc.get("type") != "list_item":
                continue
            attrs = inc.get("attributes") or {}
            items[str(inc["id"])] = {
                "id": str(inc["id"]),
                "label": attrs.get("label") or "",
                "status": "completed" if attrs.get("status") == "completed" else "pending",
                "section": attrs.get("section"),
            }
        out = []
        for item in (data or {}).get("data", []):
            attrs = item.get("attributes") or {}
            refs = ((item.get("relationships") or {}).get("list_items") or {}).get("data") or []
            out.append(
                {
                    "id": str(item["id"]),
                    "label": attrs.get("label") or str(item["id"]),
                    "kind": attrs.get("kind"),
                    "items": [items[str(r["id"])] for r in refs if str(r.get("id")) in items],
                }
            )
        return out

    async def calendar_events(
        self, frame: str, date_min: str, date_max: str, timezone: str
    ) -> list[dict[str, Any]]:
        """Events between date_min (inclusive) and date_max (exclusive)."""
        data = await self._request(
            "GET",
            f"/frames/{frame}/calendar_events",
            params={"date_min": date_min, "date_max": date_max, "timezone": timezone},
        )
        labels = {
            str(inc["id"]): (inc.get("attributes") or {}).get("label")
            for inc in (data or {}).get("included") or []
            if inc.get("type") == "category"
        }
        out = []
        for item in (data or {}).get("data", []):
            attrs = item.get("attributes") or {}
            category = _rel_id(item, "category")
            out.append(
                {
                    "id": str(item["id"]),
                    "summary": attrs.get("summary") or "",
                    "starts_at": attrs.get("starts_at"),
                    "ends_at": attrs.get("ends_at"),
                    "all_day": bool(attrs.get("all_day")),
                    "description": attrs.get("description"),
                    "location": attrs.get("location"),
                    "category_id": category,
                    "category": labels.get(category or ""),
                }
            )
        return out

    # --- writes ----------------------------------------------------------
    async def create_chore(
        self,
        frame: str,
        summary: str,
        start: str,
        category_id: str | None = None,
        reward_points: int | None = None,
        up_for_grabs: bool = False,
    ) -> str:
        """Create a one-off chore, assigned to a profile or up for grabs."""
        body: dict[str, Any] = {"summary": summary, "start": start}
        if reward_points:
            body["reward_points"] = int(reward_points)
        if up_for_grabs:
            # Unassigned chores only exist through this endpoint.
            body.update({"up_for_grabs": True, "category_ids": [], "routine": False})
            data = await self._request("POST", f"/frames/{frame}/chores/create_multiple", body=body)
        else:
            if not category_id:
                raise SkylightError("An assigned Skylight chore needs a profile")
            body["category_id"] = int(category_id) if str(category_id).isdigit() else category_id
            data = await self._request("POST", f"/frames/{frame}/chores", body=body)
        item = (data or {}).get("data")
        if isinstance(item, list):
            item = item[0] if item else None
        if not isinstance(item, dict) or not item.get("id"):
            raise SkylightError("Skylight did not return the chore it created")
        return str(item["id"])

    async def set_chore_status(
        self, frame: str, chore_id: str, status: str = "complete", category_id: str | None = None
    ) -> None:
        """Tick or un-tick a chore. category_id says who did an up-for-grabs one."""
        base = chore_id
        body: dict[str, Any] = {"status": status}
        match = re.match(r"^(\d+)-(\d{4}-\d{2}-\d{2})", chore_id)
        if match:
            base = match.group(1)
            body["instance_date"] = match.group(2)
        if category_id and status == "complete":
            body["category_id"] = int(category_id) if str(category_id).isdigit() else category_id
        await self._request("PUT", f"/frames/{frame}/chores/{base}/completions", body=body)

    async def delete_chore(self, frame: str, chore_id: str) -> None:
        params = {"apply_to": "one"} if "-" in chore_id else None
        await self._request("DELETE", f"/frames/{frame}/chores/{chore_id}", params=params)

    async def add_list_item(self, frame: str, list_id: str, label: str) -> str:
        data = await self._request(
            "POST", f"/frames/{frame}/lists/{list_id}/list_items", body={"label": label, "section": None}
        )
        item = (data or {}).get("data")
        if not isinstance(item, dict) or not item.get("id"):
            raise SkylightError("Skylight did not return the list item it created")
        return str(item["id"])

    async def update_list_item(
        self, frame: str, list_id: str, item_id: str, status: str | None = None, label: str | None = None
    ) -> None:
        body: dict[str, Any] = {}
        if status is not None:
            body["status"] = status
        if label is not None:
            body["label"] = label
        if body:
            await self._request("PUT", f"/frames/{frame}/lists/{list_id}/list_items/{item_id}", body=body)

    async def delete_list_item(self, frame: str, list_id: str, item_id: str) -> None:
        await self._request("DELETE", f"/frames/{frame}/lists/{list_id}/list_items/{item_id}")


def _rel_id(item: dict[str, Any], key: str) -> str | None:
    value = ((item.get("relationships") or {}).get(key) or {}).get("data")
    if isinstance(value, list):
        value = value[0] if value else None
    return str(value["id"]) if isinstance(value, dict) and value.get("id") else None
