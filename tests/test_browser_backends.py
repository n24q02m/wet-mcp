"""WS-2/WS-4: browser backend provider chain factory + key-gated captcha tier."""

from __future__ import annotations

from wet_mcp.config import Settings, settings
from wet_mcp.sources.crawler import _build_headless_strategies, _build_scraping_agent

# ---------------------------------------------------------------------------
# browser_backend_chain (config)
# ---------------------------------------------------------------------------


def test_browser_chain_default_native(monkeypatch):
    monkeypatch.delenv("BROWSER_BACKENDS", raising=False)
    assert Settings(
        browser_backends="", disable_local_browser=False
    ).browser_backend_chain() == ["native"]


def test_browser_chain_csv(monkeypatch):
    monkeypatch.delenv("BROWSER_BACKENDS", raising=False)
    s = Settings(
        browser_backends="cf-browser-rendering, browserless",
        disable_local_browser=False,
    )
    assert s.browser_backend_chain() == ["cf-browser-rendering", "browserless"]


def test_browser_chain_disable_local_drops_native(monkeypatch):
    monkeypatch.delenv("BROWSER_BACKENDS", raising=False)
    s = Settings(
        browser_backends="native,cf-browser-rendering", disable_local_browser=True
    )
    assert s.browser_backend_chain() == ["cf-browser-rendering"]


def test_browser_chain_env_overrides_setting(monkeypatch):
    monkeypatch.setenv("BROWSER_BACKENDS", "browserless")
    assert Settings(browser_backends="native").browser_backend_chain() == [
        "browserless"
    ]


# ---------------------------------------------------------------------------
# _build_headless_strategies (crawler factory)
# ---------------------------------------------------------------------------


def _set_browser(monkeypatch, **kwargs):
    monkeypatch.delenv("BROWSER_BACKENDS", raising=False)
    defaults = {
        "browser_backends": "native",
        "disable_local_browser": False,
        "cf_account_id": "",
        "cf_browser_rendering_token": "",
        "browserless_url": "",
        "browserless_token": "",
        "capsolver_api_key": "",
    }
    defaults.update(kwargs)
    for k, v in defaults.items():
        monkeypatch.setattr(settings, k, v, raising=False)


def test_headless_native_default(monkeypatch):
    _set_browser(monkeypatch, browser_backends="native")
    strats = _build_headless_strategies(stealth=True)
    assert "headless" in strats


def test_headless_cf_backend_when_creds_present(monkeypatch):
    _set_browser(
        monkeypatch,
        browser_backends="cf-browser-rendering",
        cf_account_id="acct",
        cf_browser_rendering_token="tok",
    )
    strats = _build_headless_strategies(stealth=True)
    assert "cf_render" in strats
    assert "headless" not in strats


def test_headless_browserless_backend(monkeypatch):
    _set_browser(
        monkeypatch,
        browser_backends="browserless",
        browserless_url="https://bl.example.com",
    )
    strats = _build_headless_strategies(stealth=True)
    assert "browserless" in strats


def test_headless_skips_missing_creds_and_falls_back_to_native(monkeypatch):
    # cf requested but no creds + local NOT disabled -> native fallback.
    _set_browser(monkeypatch, browser_backends="cf-browser-rendering")
    strats = _build_headless_strategies(stealth=True)
    assert "headless" in strats
    assert "cf_render" not in strats


def test_headless_empty_when_local_disabled_and_no_cloud_creds(monkeypatch):
    _set_browser(
        monkeypatch, browser_backends="cf-browser-rendering", disable_local_browser=True
    )
    strats = _build_headless_strategies(stealth=True)
    assert strats == {}  # gracefully no headless leg


def test_headless_chain_order_native_after_cloud(monkeypatch):
    _set_browser(
        monkeypatch,
        browser_backends="cf-browser-rendering,native",
        cf_account_id="acct",
        cf_browser_rendering_token="tok",
    )
    strats = _build_headless_strategies(stealth=True)
    assert set(strats) == {"cf_render", "headless"}


# ---------------------------------------------------------------------------
# Key-gated captcha tier (WS-4)
# ---------------------------------------------------------------------------


def test_captcha_tier_added_when_key_set(monkeypatch):
    _set_browser(monkeypatch, capsolver_api_key="CAP-xxx")
    agent = _build_scraping_agent(stealth=True)
    assert "captcha" in agent.strategies
    # Appended LAST so it is reached only after the lighter strategies.
    assert list(agent.strategies)[-1] == "captcha"


def test_captcha_tier_absent_when_no_key(monkeypatch):
    _set_browser(monkeypatch, capsolver_api_key="")
    agent = _build_scraping_agent(stealth=True)
    assert "captcha" not in agent.strategies
    assert "basic_http" in agent.strategies


def test_scraping_agent_uses_configured_robots_policy(monkeypatch):
    _set_browser(monkeypatch, respect_robots_txt=True)

    agent = _build_scraping_agent(stealth=True)

    assert agent.respect_robots is True


def test_scraping_agent_defaults_to_disabled_robots_policy(monkeypatch):
    _set_browser(monkeypatch)

    agent = _build_scraping_agent(stealth=True)

    assert agent.respect_robots is False
