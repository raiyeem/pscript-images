"""robots.txt checks and crawl delay (M10). Simple line parser; no dependencies.

Criteria keys read:
  politeness.respect_robots, politeness.ua_name (robots matching),
  politeness.user_agent (HTTP User-Agent), politeness.connect_timeout_s (robots timeout),
  politeness.delay_seconds (minimum delay between downloads)

Only the page URL's host is checked. Image CDN hosts are not checked.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

import requests

from criteria import Criteria


@dataclass(frozen=True)
class RobotsPolicy:
    disallow: tuple[str, ...]
    crawl_delay: float | None


def fetch_robots(url: str, user_agent: str, timeout: float) -> tuple[str | None, str | None]:
    """(robots text, None) when found; (None, reason) when missing or unreachable."""
    parts = urlsplit(url)
    robots_url = urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))
    try:
        response = requests.get(robots_url, headers={"User-Agent": user_agent}, timeout=timeout)
    except requests.RequestException as exc:
        return (None, f"robots.txt unreachable ({type(exc).__name__}); proceeding")
    if response.status_code != 200:
        return (None, f"robots.txt returned HTTP {response.status_code}; proceeding")
    return (response.text, None)


def parse_robots(text: str, ua_name: str) -> RobotsPolicy:
    """Rules for ua_name, or for '*' when no group names ua_name."""
    groups: list[dict] = []
    current: dict | None = None
    last_was_agent = False
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if current is None or not last_was_agent:
                current = {"agents": [], "disallow": [], "crawl_delay": None}
                groups.append(current)
            current["agents"].append(value.lower())
            last_was_agent = True
            continue
        last_was_agent = False
        if current is None:
            continue
        if key == "disallow":
            current["disallow"].append(value)
        elif key == "crawl-delay":
            try:
                current["crawl_delay"] = float(value)
            except ValueError:
                pass

    name = ua_name.lower()
    specific = [g for g in groups if name in g["agents"]]
    chosen = specific or [g for g in groups if "*" in g["agents"]]
    disallow = tuple(rule for group in chosen for rule in group["disallow"] if rule)
    delays = [g["crawl_delay"] for g in chosen if g["crawl_delay"] is not None]
    return RobotsPolicy(disallow=disallow, crawl_delay=delays[0] if delays else None)


def blocking_rule(policy: RobotsPolicy, url: str) -> str | None:
    """The first Disallow prefix that matches the URL's path, or None."""
    path = urlsplit(url).path or "/"
    for rule in policy.disallow:
        if path.startswith(rule):
            return rule
    return None


def effective_delay(criteria: Criteria, crawl_delay: float | None) -> float:
    """Larger of politeness.delay_seconds and the robots Crawl-delay."""
    return max(criteria.politeness.delay_seconds, crawl_delay or 0.0)
