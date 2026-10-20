"""Email templates: one JSON file per template in templates/.

Each template defines its recipients, audience, topics (with feed sources),
learning tracks and challenge types. See README for the schema.
"""

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

TEMPLATE_DIR = Path(__file__).parent / "templates"
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
ENV_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
EMAIL_RE = re.compile(r"^[^@\s,]+@[^@\s,]+\.[^@\s,]+$")
HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
# Fixed-order fallback colors for topics that don't set one
DEFAULT_COLORS = ["#6d28d9", "#0369a1", "#c2410c", "#047857", "#a16207", "#be185d", "#0891b2", "#65a30d"]
# Keys the story-selection JSON already uses
RESERVED_KEYS = {"top", "quick_hits"}
DEFAULT_CHALLENGE = "A practical problem the reader can solve in about 15 minutes"


class TemplateError(Exception):
    pass


@dataclass
class Source:
    name: str
    url: str
    topic: str
    slow: bool


@dataclass
class Topic:
    key: str
    label: str
    color: str
    focus: str


@dataclass
class Track:
    key: str
    name: str
    lessons: list[str]


@dataclass
class Template:
    id: str
    name: str
    enabled: bool
    recipients: list[str]
    recipients_env: str
    days: list[str]
    audience: str
    topics: dict[str, Topic]
    sources: list[Source]
    learning_goal: str
    tracks: list[Track]
    challenge_types: list[str]

    def sends_on(self, weekday: int) -> bool:
        return DAYS[weekday] in self.days


def _require(cond: bool, where: str, msg: str) -> None:
    if not cond:
        raise TemplateError(f"{where}: {msg}")


def parse_recipients(raw, where: str, echo: bool = True) -> list[str]:
    """echo=False keeps addresses out of error messages (for values read from secrets, which end up in public logs)."""
    _require(raw is None or isinstance(raw, (str, list)), where, '"recipients" must be a comma-separated string')
    items = raw if isinstance(raw, list) else (raw or "").split(",")
    _require(all(isinstance(e, str) for e in items), where, '"recipients" must contain only strings')
    emails = [e.strip() for e in items if e.strip()]
    bad = [e for e in emails if not EMAIL_RE.match(e)]
    _require(not bad, where, f"invalid recipient(s): {', '.join(bad)}" if echo
             else f"{len(bad)} invalid email address(es), check the secret")
    return list(dict.fromkeys(emails))


def _opt_str(data: dict, key: str, where: str, default: str = "") -> str:
    value = data.get(key)
    _require(value is None or isinstance(value, str), where, f'"{key}" must be a string')
    return value.strip() if value else default


def _str_list(data: dict, key: str, where: str) -> list[str]:
    value = data.get(key)
    _require(value is None or (isinstance(value, list) and all(isinstance(x, str) for x in value)),
             where, f'"{key}" must be a list of strings')
    return [x.strip() for x in value or [] if x.strip()]


def _parse(tid: str, data) -> Template:
    where = f"templates/{tid}.json"
    _require(ID_RE.match(tid) is not None, where, "file name must be lowercase letters, digits, - or _")
    _require(isinstance(data, dict), where, "must be a JSON object")
    name = _opt_str(data, "name", where)
    _require(name != "", where, '"name" is required')

    enabled = data.get("enabled", True)
    _require(isinstance(enabled, bool), where, '"enabled" must be true or false (no quotes)')
    # Recipients can sit in the file ("recipients") and/or in an environment variable ("recipients_env"),
    # so a public repo can keep addresses in a secret. An empty list is caught at send time, which keeps
    # dry runs and the feed health check working without the secret.
    recipients = parse_recipients(data.get("recipients"), where)
    recipients_env = _opt_str(data, "recipients_env", where)
    _require(recipients_env == "" or ENV_RE.match(recipients_env) is not None, where,
             '"recipients_env" must be an UPPER_SNAKE_CASE variable name')
    if recipients_env:
        from_env = parse_recipients(os.environ.get(recipients_env), f"{where} env var {recipients_env}", echo=False)
        recipients = list(dict.fromkeys(recipients + from_env))

    days = [d.lower()[:3] for d in _str_list(data, "days", where)] if "days" in data else list(DAYS)
    _require(bool(days) and all(d in DAYS for d in days), where, f'"days" must use {DAYS}')

    raw_topics = data.get("topics")
    _require(isinstance(raw_topics, dict) and bool(raw_topics), where, '"topics" must be a non-empty object')
    topics, sources = {}, []
    for i, (key, t) in enumerate(raw_topics.items()):
        tw = f"{where} topic {key!r}"
        _require(ID_RE.match(key) is not None and key not in RESERVED_KEYS, tw,
                 f"key must be lowercase and not one of {sorted(RESERVED_KEYS)}")
        _require(isinstance(t, dict), tw, "must be an object")
        color = _opt_str(t, "color", tw, DEFAULT_COLORS[i % len(DEFAULT_COLORS)])
        _require(HEX_RE.match(color) is not None, tw, "color must look like #1a2b3c")
        topics[key] = Topic(key, _opt_str(t, "label", tw, key.title()), color, _opt_str(t, "focus", tw))
        feeds = t.get("sources")
        _require(isinstance(feeds, list) and bool(feeds), tw, '"sources" needs at least one feed')
        for f in feeds:
            _require(isinstance(f, dict) and isinstance(f.get("url"), str) and f["url"].startswith("http"),
                     tw, f"bad source {f!r}")
            slow = f.get("slow", False)
            _require(isinstance(slow, bool), tw, f'"slow" must be true or false in {f!r}')
            sources.append(Source(_opt_str(f, "name", tw, f["url"]), f["url"], key, slow))

    learning = data.get("learning", {})
    _require(isinstance(learning, dict), where, '"learning" must be an object')
    raw_tracks = learning.get("tracks", [])
    _require(isinstance(raw_tracks, list), where, '"learning.tracks" must be a list')
    tracks = []
    for tr in raw_tracks:
        _require(isinstance(tr, dict), where, "each track must be an object")
        key, tname = _opt_str(tr, "key", where), _opt_str(tr, "name", where)
        _require(key != "" and tname != "", where, "each track needs key and name")
        tracks.append(Track(key, tname, _str_list(tr, "lessons", f"{where} track {key!r}")))
    _require(len({t.key for t in tracks}) == len(tracks), where, "track keys must be unique")

    return Template(
        id=tid,
        name=name,
        enabled=enabled,
        recipients=recipients,
        recipients_env=recipients_env,
        days=days,
        audience=_opt_str(data, "audience", where, "a curious professional who wants to stay current and keep learning"),
        topics=topics,
        sources=sources,
        learning_goal=_opt_str(learning, "goal", where, "fundamentals plus a working understanding"),
        tracks=tracks,
        challenge_types=_str_list(data, "challenge_types", where) or [DEFAULT_CHALLENGE],
    )


def load_all() -> list[Template]:
    templates = []
    for path in sorted(TEMPLATE_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError as e:
            raise TemplateError(f"templates/{path.name}: invalid JSON ({e})") from e
        templates.append(_parse(path.stem, data))
    if not templates:
        raise TemplateError("no templates found in templates/")
    return templates
