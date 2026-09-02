"""Pluggable web-search backends. Default SearXNG (local), Tavily (cloud) for CF
where SearXNG cannot run. All return the same JSON string {results, total, query}
| {error} that server.py's search action already expects from searxng.search().

Each cloud backend takes a LIST of API keys (CSV in the env): a single key keeps
exactly today's behaviour, while multiple keys rotate automatically on a
key-specific failure (HTTP 429 rate-limit / 401-403 auth) via the shared
``mcp_core.llm.key_rotation`` primitive. An empty result from a working key is
legitimate and never triggers rotation — only the PROVIDER chain advances on empty.
"""

from __future__ import annotations

import json
import os
from collections.abc import Awaitable, Callable
from typing import Protocol

import httpx
from loguru import logger
from mcp_core.chains import run_with_fallback
from mcp_core.llm.key_rotation import rotate_keys, split_keys

from wet_mcp.config import settings


class SearchBackend(Protocol):
    name: str

    async def search(
        self,
        query: str,
        max_results: int = 10,
        time_range: str | None = None,
        language: str | None = None,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
        categories: str = "general",
        region: str | None = None,
    ) -> str: ...


class _SearchHTTPError(Exception):
    """A non-2xx response from a search provider, carrying ``status_code`` so
    ``mcp_core.llm.key_rotation`` classifies 429/401/403 as a rotatable
    (key-specific) failure and advances to the next key. The message is the safe
    ``"<Provider> HTTP <code>"`` form — it never carries the request body/key."""

    def __init__(self, provider: str, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"{provider} HTTP {status_code}")


async def _search_with_rotation(
    keys: list[str],
    attempt: Callable[[str], Awaitable[str]],
    provider: str,
) -> str:
    """Rotate ``keys`` for one search provider, advancing only on a key-specific
    failure (429/401/403). Returns the tool-contract error envelope when keys are
    exhausted or a non-rotatable error occurs — type name only, never the
    exception text (an httpx error may carry the request body, i.e. the key)."""
    if not keys:
        return json.dumps({"error": f"{provider} search backend has no API key"})
    try:
        return await rotate_keys(keys, attempt, label=provider.lower())
    except _SearchHTTPError as exc:
        return json.dumps(
            {"error": str(exc)}
        )  # "<Provider> HTTP <code>" — safe, no key
    except (
        httpx.HTTPError
    ) as exc:  # transport — type name only (never echo, may carry the key)
        return json.dumps({"error": f"{provider} request failed: {type(exc).__name__}"})
    except Exception as exc:  # tool contract: error string, never raise; type name only
        return json.dumps({"error": f"{provider} search failed: {type(exc).__name__}"})


# Backends with native geo/region support. ``region`` is an ISO 3166-1 alpha-2
# code (``"US"``, ``"vn"``). A backend outside this set never receives the
# value silently: the chain skips it with a warning naming it, and when no
# configured backend supports it the caller gets a structured error naming
# them. The region is never silently dropped.
_REGION_SUPPORTED_BACKENDS = frozenset({"searxng", "brave", "tavily"})


def _searxng_locale(language: str | None, region: str | None) -> str | None:
    """Map ``language`` + ``region`` onto SearXNG's single ``language`` locale.

    SearXNG takes one ``language`` parameter in ``<lang>-<REGION>`` form, so
    ``language="vi", region="vn"`` -> ``"vi-VN"``; a bare region passes
    through as-is.
    """
    if region and language:
        return f"{language}-{region.upper()}"
    if region:
        return region.upper()
    return language


# Tavily's ``country`` parameter is a closed enum of lowercase country names
# (docs.tavily.com API reference, enum extracted 2026-09-02), so an ISO
# 3166-1 alpha-2 ``region`` must map through this table. A code Tavily does
# not carry yields an explicit error naming the backend -- never a silent
# drop of the geo filter.
_TAVILY_COUNTRY_BY_ISO: dict[str, str] = {
    "af": "afghanistan",
    "al": "albania",
    "dz": "algeria",
    "ad": "andorra",
    "ao": "angola",
    "ar": "argentina",
    "am": "armenia",
    "au": "australia",
    "at": "austria",
    "az": "azerbaijan",
    "bs": "bahamas",
    "bh": "bahrain",
    "bd": "bangladesh",
    "bb": "barbados",
    "by": "belarus",
    "be": "belgium",
    "bz": "belize",
    "bj": "benin",
    "bt": "bhutan",
    "bo": "bolivia",
    "ba": "bosnia and herzegovina",
    "bw": "botswana",
    "br": "brazil",
    "bn": "brunei",
    "bg": "bulgaria",
    "bf": "burkina faso",
    "bi": "burundi",
    "kh": "cambodia",
    "cm": "cameroon",
    "ca": "canada",
    "cv": "cape verde",
    "cf": "central african republic",
    "td": "chad",
    "cl": "chile",
    "cn": "china",
    "co": "colombia",
    "km": "comoros",
    "cg": "congo",
    "cr": "costa rica",
    "hr": "croatia",
    "cu": "cuba",
    "cy": "cyprus",
    "cz": "czech republic",
    "dk": "denmark",
    "dj": "djibouti",
    "do": "dominican republic",
    "ec": "ecuador",
    "eg": "egypt",
    "sv": "el salvador",
    "gq": "equatorial guinea",
    "er": "eritrea",
    "ee": "estonia",
    "et": "ethiopia",
    "fj": "fiji",
    "fi": "finland",
    "fr": "france",
    "ga": "gabon",
    "gm": "gambia",
    "ge": "georgia",
    "de": "germany",
    "gh": "ghana",
    "gr": "greece",
    "gt": "guatemala",
    "gn": "guinea",
    "ht": "haiti",
    "hn": "honduras",
    "hu": "hungary",
    "is": "iceland",
    "in": "india",
    "id": "indonesia",
    "ir": "iran",
    "iq": "iraq",
    "ie": "ireland",
    "il": "israel",
    "it": "italy",
    "jm": "jamaica",
    "jp": "japan",
    "jo": "jordan",
    "kz": "kazakhstan",
    "ke": "kenya",
    "kw": "kuwait",
    "kg": "kyrgyzstan",
    "lv": "latvia",
    "lb": "lebanon",
    "ls": "lesotho",
    "lr": "liberia",
    "ly": "libya",
    "li": "liechtenstein",
    "lt": "lithuania",
    "lu": "luxembourg",
    "mg": "madagascar",
    "mw": "malawi",
    "my": "malaysia",
    "mv": "maldives",
    "ml": "mali",
    "mt": "malta",
    "mr": "mauritania",
    "mu": "mauritius",
    "mx": "mexico",
    "md": "moldova",
    "mc": "monaco",
    "mn": "mongolia",
    "me": "montenegro",
    "ma": "morocco",
    "mz": "mozambique",
    "mm": "myanmar",
    "na": "namibia",
    "np": "nepal",
    "nl": "netherlands",
    "nz": "new zealand",
    "ni": "nicaragua",
    "ne": "niger",
    "ng": "nigeria",
    "kp": "north korea",
    "mk": "north macedonia",
    "no": "norway",
    "om": "oman",
    "pk": "pakistan",
    "pa": "panama",
    "pg": "papua new guinea",
    "py": "paraguay",
    "pe": "peru",
    "ph": "philippines",
    "pl": "poland",
    "pt": "portugal",
    "qa": "qatar",
    "ro": "romania",
    "ru": "russia",
    "rw": "rwanda",
    "sa": "saudi arabia",
    "sn": "senegal",
    "rs": "serbia",
    "sg": "singapore",
    "sk": "slovakia",
    "si": "slovenia",
    "so": "somalia",
    "za": "south africa",
    "kr": "south korea",
    "ss": "south sudan",
    "es": "spain",
    "lk": "sri lanka",
    "sd": "sudan",
    "se": "sweden",
    "ch": "switzerland",
    "sy": "syria",
    "tw": "taiwan",
    "tj": "tajikistan",
    "tz": "tanzania",
    "th": "thailand",
    "tg": "togo",
    "tt": "trinidad and tobago",
    "tn": "tunisia",
    "tr": "turkey",
    "tm": "turkmenistan",
    "ug": "uganda",
    "ua": "ukraine",
    "ae": "united arab emirates",
    "gb": "united kingdom",
    "us": "united states",
    "uy": "uruguay",
    "uz": "uzbekistan",
    "ve": "venezuela",
    "vn": "vietnam",
    "ye": "yemen",
    "zm": "zambia",
    "zw": "zimbabwe",
}


class SearxngBackend:
    name = "searxng"

    def __init__(self, url: str) -> None:
        self.url = url

    async def search(
        self,
        query: str,
        max_results: int = 10,
        time_range=None,
        language=None,
        include_domains=None,
        exclude_domains=None,
        categories="general",
        region=None,
    ) -> str:
        from wet_mcp.sources.searxng import search as searxng_search

        return await searxng_search(
            searxng_url=self.url,
            query=query,
            categories=categories,
            max_results=max_results,
            time_range=time_range,
            language=_searxng_locale(language, region),
            include_domains=include_domains,
            exclude_domains=exclude_domains,
        )


class TavilyBackend:
    name = "tavily"

    _URL = "https://api.tavily.com/search"

    def __init__(self, keys: list[str]) -> None:
        self.keys = keys

    async def _search_one(self, key, query, max_results, country=None) -> str:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                self._URL,
                json={
                    "api_key": key,
                    "query": query,
                    "max_results": max_results,
                    "search_depth": "basic",
                    **({"country": country} if country else {}),
                },
            )
            if resp.status_code != 200:
                raise _SearchHTTPError("Tavily", resp.status_code)
            results = resp.json().get("results", [])
            mapped = [
                {
                    "url": r.get("url", ""),
                    "title": r.get("title", ""),
                    "snippet": r.get("content", r.get("title", "")),
                    "source": "tavily",
                }
                for r in results
            ]
            return json.dumps(
                {"results": mapped, "total": len(mapped), "query": query},
                ensure_ascii=False,
                indent=2,
            )

    async def search(
        self,
        query: str,
        max_results: int = 10,
        time_range=None,
        language=None,
        include_domains=None,
        exclude_domains=None,
        categories="general",
        region=None,
    ) -> str:
        if region:
            country = _TAVILY_COUNTRY_BY_ISO.get(region.lower())
            if country is None:
                # Explicit, structured, backend-named: never silently drop
                # the requested geo filter.
                return json.dumps(
                    {
                        "error": (
                            f"tavily does not support region={region!r}: "
                            "not a code in Tavily's country list"
                        )
                    },
                    ensure_ascii=False,
                )
        else:
            country = None
        return await _search_with_rotation(
            self.keys,
            lambda key: self._search_one(key, query, max_results, country),
            "Tavily",
        )


class BraveBackend:
    """Brave Web Search API (https://api.search.brave.com/res/v1/web/search).

    GET with header ``X-Subscription-Token``; results live at ``web.results[]``
    (verified against current Brave docs 2026-06-19).
    """

    name = "brave"

    _URL = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, keys: list[str]) -> None:
        self.keys = keys

    async def _search_one(
        self, key, query, max_results, time_range, language, region=None
    ) -> str:
        params: dict[str, str | int] = {
            "q": query,
            "count": min(max(max_results, 1), 20),
        }
        if time_range:
            # Brave freshness codes: pd (day) / pw (week) / pm (month) / py (year).
            freshness = {"day": "pd", "week": "pw", "month": "pm", "year": "py"}.get(
                time_range
            )
            if freshness:
                params["freshness"] = freshness
        if language:
            params["search_lang"] = language
        if region:
            # Brave expects a 2-char ISO 3166-1 alpha-2 country code.
            params["country"] = region.upper()
        headers = {"X-Subscription-Token": key, "Accept": "application/json"}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(self._URL, params=params, headers=headers)
            if resp.status_code != 200:
                raise _SearchHTTPError("Brave", resp.status_code)
            results = resp.json().get("web", {}).get("results", [])
            mapped = [
                {
                    "url": r.get("url", ""),
                    "title": r.get("title", ""),
                    "snippet": r.get("description", r.get("title", "")),
                    "source": "brave",
                }
                for r in results
            ]
            return json.dumps(
                {"results": mapped, "total": len(mapped), "query": query},
                ensure_ascii=False,
                indent=2,
            )

    async def search(
        self,
        query: str,
        max_results: int = 10,
        time_range=None,
        language=None,
        include_domains=None,
        exclude_domains=None,
        categories="general",
        region=None,
    ) -> str:
        return await _search_with_rotation(
            self.keys,
            lambda key: self._search_one(
                key, query, max_results, time_range, language, region
            ),
            "Brave",
        )


class ExaBackend:
    """Exa search API (https://api.exa.ai/search).

    POST with header ``x-api-key``; body ``{query, numResults}`` plus a small
    ``contents.text`` request so each result carries a snippet. Results live at
    ``results[]`` (verified against current Exa docs 2026-06-19).
    """

    name = "exa"

    _URL = "https://api.exa.ai/search"

    def __init__(self, keys: list[str]) -> None:
        self.keys = keys

    async def _search_one(
        self, key, query, max_results, include_domains, exclude_domains
    ) -> str:
        body: dict[str, object] = {
            "query": query,
            "numResults": min(max(max_results, 1), 100),
            "contents": {"text": {"maxCharacters": 300}},
        }
        if include_domains:
            body["includeDomains"] = include_domains
        if exclude_domains:
            body["excludeDomains"] = exclude_domains
        headers = {"x-api-key": key, "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(self._URL, json=body, headers=headers)
            if resp.status_code != 200:
                raise _SearchHTTPError("Exa", resp.status_code)
            results = resp.json().get("results", [])
            mapped = [
                {
                    "url": r.get("url", ""),
                    "title": r.get("title", ""),
                    "snippet": (r.get("text") or r.get("title", ""))[:300],
                    "source": "exa",
                }
                for r in results
            ]
            return json.dumps(
                {"results": mapped, "total": len(mapped), "query": query},
                ensure_ascii=False,
                indent=2,
            )

    async def search(
        self,
        query: str,
        max_results: int = 10,
        time_range=None,
        language=None,
        include_domains=None,
        exclude_domains=None,
        categories="general",
        region=None,
    ) -> str:
        if region:
            # Exa's /search API has no geo parameter. Structured error naming
            # the backend so the chain advances (or the caller sees) instead
            # of silently searching without the requested region.
            return json.dumps(
                {"error": f"exa does not support region filtering (region={region!r})"},
                ensure_ascii=False,
            )
        return await _search_with_rotation(
            self.keys,
            lambda key: self._search_one(
                key, query, max_results, include_domains, exclude_domains
            ),
            "Exa",
        )


def _make_backend(name: str, searxng_url: str | None = None) -> SearchBackend:
    """Construct a single backend by name. Raises ValueError on missing key/unknown.

    ``searxng_url`` overrides ``settings.searxng_url`` for the SearXNG backend
    (the live auto-started URL, which may use a dynamic port) without mutating
    the global settings. Cloud backends read a CSV of keys (``split_keys``): a
    single key is unchanged, multiple keys rotate on rate-limit/auth failure.
    """
    if name == "searxng":
        return SearxngBackend(searxng_url or settings.searxng_url)
    if name == "tavily":
        keys = split_keys(os.getenv("TAVILY_API_KEY", settings.tavily_api_key))
        if not keys:
            raise ValueError("TAVILY_API_KEY required for the tavily search backend")
        return TavilyBackend(keys)
    if name == "brave":
        keys = split_keys(os.getenv("BRAVE_API_KEY", settings.brave_api_key))
        if not keys:
            raise ValueError("BRAVE_API_KEY required for the brave search backend")
        return BraveBackend(keys)
    if name == "exa":
        keys = split_keys(os.getenv("EXA_API_KEY", settings.exa_api_key))
        if not keys:
            raise ValueError("EXA_API_KEY required for the exa search backend")
        return ExaBackend(keys)
    raise ValueError(f"Unknown search backend: {name}")


def search_backend_from_env() -> SearchBackend:
    """Single-backend resolver (back-compat). Raises on missing key/unknown name."""
    name = (os.getenv("SEARCH_BACKEND", settings.search_backend) or "searxng").lower()
    return _make_backend(name)


# The local SearXNG auto-spawn URL (mirrors the ``searxng_url`` default in
# config.py). A uvx tool venv has no pip, so it cannot auto-start this
# instance; any other URL means an already-running external SearXNG reachable
# over HTTP, which uvx can use.
_DEFAULT_LOCAL_SEARXNG_URL = "http://localhost:41592"


def has_uvx_runnable_backend() -> bool:
    """Whether the configured ``SEARCH_BACKENDS`` chain has >=1 backend that
    can run under uvx (a tool venv with no pip, so the local SearXNG cannot
    auto-spawn).

    ``tavily``/``brave``/``exa`` are runnable whenever their API key is
    present -- they call out via ``httpx`` directly, no SearXNG needed (same
    live-env-first key lookup ``_make_backend`` uses). ``searxng`` is
    runnable under uvx only when ``SEARXNG_URL`` points at an already-running
    external instance; the default local URL implies the auto-spawn, which
    uvx tool venvs cannot start.
    """
    for name in chain_backend_names():
        if name == "tavily" and split_keys(
            os.getenv("TAVILY_API_KEY", settings.tavily_api_key)
        ):
            return True
        if name == "brave" and split_keys(
            os.getenv("BRAVE_API_KEY", settings.brave_api_key)
        ):
            return True
        if name == "exa" and split_keys(os.getenv("EXA_API_KEY", settings.exa_api_key)):
            return True
        if name == "searxng":
            url = os.getenv("SEARXNG_URL", settings.searxng_url)
            if url != _DEFAULT_LOCAL_SEARXNG_URL:
                return True
    return False


def chain_backend_names() -> list[str]:
    """The ordered backend names in the chain (no construction, no keys needed).

    Reads the CSV ``SEARCH_BACKENDS``; empty -> the single ``SEARCH_BACKEND``
    (back-compat). Used to decide whether the embedded SearXNG must be started
    before running the chain.
    """
    raw = (os.getenv("SEARCH_BACKENDS", settings.search_backends) or "").strip()
    if not raw:
        raw = (
            os.getenv("SEARCH_BACKEND", settings.search_backend) or "searxng"
        ).strip()
    return [n.strip().lower() for n in raw.split(",") if n.strip()]


def search_backends_from_env(searxng_url: str | None = None) -> list[SearchBackend]:
    """Resolve the ordered SEARCH_BACKENDS chain.

    Reads the CSV ``SEARCH_BACKENDS``; empty -> falls back to the single
    ``SEARCH_BACKEND`` (back-compat). Backends that cannot be built (missing
    key) are SKIPPED with a warning so a partially-configured chain still works
    with whatever providers are available. ``searxng_url`` overrides the SearXNG
    backend URL (the live auto-started instance).
    """
    backends: list[SearchBackend] = []
    for name in chain_backend_names():
        try:
            backends.append(_make_backend(name, searxng_url))
        except ValueError as exc:
            logger.warning(f"Skipping search backend {name!r}: {exc}")
    return backends


def _search_result_is_empty(payload: str) -> bool:
    """A search result JSON string counts as empty (advance the chain) when it
    is an error envelope, malformed, or carries no results."""
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, TypeError):
        return True
    if not isinstance(data, dict):
        return True
    if data.get("error"):
        return True
    results = data.get("results")
    if not isinstance(results, list):
        return True
    return not results


def _search_result_has_failure(payload: str) -> bool:
    """Return whether a provider outcome is an error or malformed payload."""
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, TypeError):
        return True
    return not (
        isinstance(data, dict)
        and not data.get("error")
        and isinstance(data.get("results"), list)
    )


async def run_search_chain(
    query: str,
    max_results: int = 10,
    time_range=None,
    language=None,
    include_domains=None,
    exclude_domains=None,
    categories="general",
    searxng_url: str | None = None,
    region: str | None = None,
) -> str:
    """Run the configured search chain and report the selected backend.

    Providers are tried in order. Errors and empty results advance the chain.
    The returned envelope records requested, attempted, selected, and fallback
    state without exposing provider credentials or endpoints.

    ``region`` (ISO 3166-1 alpha-2) is forwarded only to backends with native
    geo support (searxng / brave / tavily). A backend without support is
    skipped with a warning naming it; when no configured backend supports it,
    a structured error naming them is returned -- the geo filter is never
    silently dropped.
    """
    requested = chain_backend_names()
    backends = search_backends_from_env(searxng_url)
    if region and backends:
        unsupported = [
            b.name for b in backends if b.name not in _REGION_SUPPORTED_BACKENDS
        ]
        if unsupported:
            logger.warning(
                f"region={region!r} not supported by search backend(s): "
                f"{', '.join(unsupported)}; skipping them"
            )
            backends = [b for b in backends if b.name in _REGION_SUPPORTED_BACKENDS]
        if not backends:
            return json.dumps(
                {
                    "results": [],
                    "total": 0,
                    "query": query,
                    "error": (
                        f"region={region!r} is not supported by search "
                        f"backend(s): {', '.join(unsupported)}"
                    ),
                    "search_backend": {
                        "requested": requested,
                        "attempted": [],
                        "selected": None,
                        "fallback": "unavailable",
                    },
                },
                ensure_ascii=False,
            )
    if not backends:
        msg = (
            f"Search backends {requested} are missing API keys; configure a key or add searxng"
            if requested
            else "No search backend configured"
        )
        return json.dumps(
            {
                "results": [],
                "total": 0,
                "query": query,
                "error": msg,
                "search_backend": {
                    "requested": requested,
                    "attempted": [],
                    "selected": None,
                    "fallback": "unavailable",
                },
            },
            ensure_ascii=False,
        )

    attempted: list[str] = []
    selected: str | None = None
    had_provider_failure = False

    def traced_thunk(backend: SearchBackend) -> Callable[[], Awaitable[str]]:
        async def invoke() -> str:
            nonlocal had_provider_failure, selected
            attempted.append(backend.name)
            try:
                payload = await backend.search(
                    query=query,
                    max_results=max_results,
                    time_range=time_range,
                    language=language,
                    include_domains=include_domains,
                    exclude_domains=exclude_domains,
                    categories=categories,
                    region=region,
                )
            except Exception:
                had_provider_failure = True
                raise
            if _search_result_has_failure(payload):
                had_provider_failure = True
            elif not _search_result_is_empty(payload):
                selected = backend.name
            return payload

        return invoke

    result = await run_with_fallback(
        [traced_thunk(backend) for backend in backends],
        is_empty=_search_result_is_empty,
        on_error=lambda idx, exc: logger.warning(
            f"Search backend #{idx} raised: {type(exc).__name__}"
        ),
    )

    data: dict[str, object] = (
        json.loads(result)
        if result is not None
        else {"results": [], "total": 0, "query": query}
    )
    if selected is None and had_provider_failure:
        data["error"] = "Search backend chain exhausted after provider failure"
    data["search_backend"] = {
        "requested": requested,
        "attempted": attempted,
        "selected": selected,
        "fallback": (
            "exhausted"
            if selected is None
            else ("none" if requested and selected == requested[0] else "used")
        ),
    }
    return json.dumps(data, ensure_ascii=False)


__all__ = [
    "BraveBackend",
    "ExaBackend",
    "SearchBackend",
    "SearxngBackend",
    "TavilyBackend",
    "chain_backend_names",
    "has_uvx_runnable_backend",
    "run_search_chain",
    "search_backend_from_env",
    "search_backends_from_env",
]
