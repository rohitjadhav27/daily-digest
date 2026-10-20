"""Email rendering: inline-styled HTML (Gmail-safe) plus a plain-text alternative.

Gmail strips SVG, scripts and most <style> rules, so every visual here is built from
tables, inline styles and remote images.
"""

from html import escape
from typing import NamedTuple

from templates import Template

INK = "#16161d"
MUTED = "#6b6b76"
LINE = "#e7e5ee"
PAGE = "#eeedf3"
PANEL = "#f7f6fb"
ACCENT = "#4f46e5"        # chart and meter fill
ACCENT_TRACK = "#e0e0fb"  # meter track, lighter step of the same hue
ACCENT_TINT = "#eef0ff"

# Per-template topic styles: topic key -> TopicStyle. Built once per render and passed down.
Styles = dict[str, "TopicStyle"]
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
PAD = "28px"


def e(text) -> str:
    return escape(str(text or ""))


def _mix(hex_color: str, weight: float) -> str:
    """Blends a color toward white; weight 0 keeps it, 1 is white."""
    rgb = [int(hex_color[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(c + (255 - c) * weight):02x}" for c in rgb)


class TopicStyle(NamedTuple):
    label: str
    color: str  # accent
    tint: str   # light panel background
    dot: str    # lighter shade that stays visible on the dark header


def topic_styles(t: Template) -> Styles:
    return {key: TopicStyle(topic.label, topic.color, _mix(topic.color, 0.9), _mix(topic.color, 0.45))
            for key, topic in t.topics.items()}


def _topic(ts: Styles, topic: str) -> TopicStyle:
    return ts.get(topic) or TopicStyle(topic or "", MUTED, "#f1f1f4", "#d9d8e3")


def _section_title(ts: Styles, key: str) -> str:
    return "Top stories" if key == "top" else _topic(ts, key).label


def _pill(ts: Styles, topic: str) -> str:
    label, color, bg, _ = _topic(ts, topic)
    return (f'<span style="display:inline-block;font-size:11px;font-weight:700;letter-spacing:.04em;'
            f'text-transform:uppercase;color:{color};background:{bg};padding:3px 8px;border-radius:999px;">'
            f'{e(label)}</span>')


def _kicker(text: str, color: str = MUTED) -> str:
    return (f'<div style="font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;'
            f'color:{color};margin-bottom:6px;">{e(text)}</div>')


def _section_head(title: str, color: str = INK, kicker: str = "") -> str:
    return (f'<tr><td style="padding:32px {PAD} 6px;">{_kicker(kicker) if kicker else ""}'
            f'<table role="presentation" cellpadding="0" cellspacing="0"><tr>'
            f'<td style="width:6px;background:{color};border-radius:3px;">&nbsp;</td>'
            f'<td style="padding-left:10px;font-size:20px;font-weight:800;letter-spacing:-.01em;line-height:1.3;color:{INK};">{e(title)}</td>'
            f'</tr></table></td></tr>')


def _paras(texts, size=15, color=INK) -> str:
    if isinstance(texts, str):
        texts = [texts]
    return "".join(f'<p style="margin:0 0 12px;font-size:{size}px;line-height:1.65;color:{color};">{e(t)}</p>'
                   for t in texts or [] if t)


def _bullets(items, color=INK, size=14) -> str:
    lis = "".join(f'<li style="margin:0 0 6px;">{e(i)}</li>' for i in items or [] if i)
    return (f'<ul style="margin:0 0 12px;padding-left:20px;font-size:{size}px;line-height:1.6;color:{color};">{lis}</ul>'
            if lis else "")


def _label(text: str, color: str = MUTED) -> str:
    return (f'<div style="font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;'
            f'color:{color};margin:16px 0 6px;">{e(text)}</div>')


def _meter(done: int, total: int, width: str = "100%") -> str:
    pct = max(0, min(100, round(done / total * 100))) if total else 0
    fill = (f'<td width="{pct}%" style="background:{ACCENT};height:8px;border-radius:4px;font-size:0;line-height:0;">&nbsp;</td>'
            if pct else "")
    rest = '<td style="font-size:0;line-height:0;">&nbsp;</td>' if pct < 100 else ""
    return (f'<table role="presentation" width="{width}" cellpadding="0" cellspacing="0" '
            f'style="background:{ACCENT_TRACK};border-radius:4px;"><tr>{fill}{rest}</tr></table>')


# ---------- header ----------

def _header(d: dict, t: Template, ts: Styles) -> str:
    counts = {}
    for section in d["sections"]:
        for s in section["items"]:
            counts[s["topic"]] = counts.get(s["topic"], 0) + 1
    chips = "".join(
        f'<span style="display:inline-block;margin:0 6px 6px 0;padding:4px 10px;border-radius:999px;'
        f'background:#26262f;font-size:12px;color:#d9d8e3;">'
        f'<span style="color:{_topic(ts, k).dot};">&#9679;</span> {e(_topic(ts, k).label)} {n}</span>'
        for k, n in counts.items())

    tldr = ""
    if d.get("tldr"):
        rows = "".join(
            f'<tr><td valign="top" style="padding:0 12px 12px 0;width:24px;">'
            f'<div style="width:24px;height:24px;border-radius:12px;background:{ACCENT};color:#ffffff;'
            f'font-size:12px;font-weight:700;line-height:24px;text-align:center;">{i}</div></td>'
            f'<td valign="top" style="padding:0 0 12px;font-size:15px;line-height:1.5;color:#ffffff;">{e(t)}</td></tr>'
            for i, t in enumerate(d["tldr"], 1))
        tldr = (f'<div style="background:#23232d;border-radius:12px;padding:16px 16px 4px;margin-top:18px;">'
                f'{_kicker("TL;DR", "#a5a3b8")}'
                f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{rows}</table></div>')

    return f"""
<tr><td style="background:{INK};padding:26px {PAD} 24px;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
    <td style="font-size:12px;font-weight:800;letter-spacing:.14em;text-transform:uppercase;color:#a5a3b8;">{e(t.name)}</td>
    <td align="right" style="font-size:12px;color:#a5a3b8;">Issue #{d.get("issue", 1)} · {d["read_minutes"]} min read</td>
  </tr></table>
  <div style="font-size:28px;font-weight:800;letter-spacing:-.02em;line-height:1.2;color:#ffffff;margin:14px 0 14px;">{e(d["date_label"])}</div>
  <div>{chips}</div>
  {tldr}
</td></tr>"""


# ---------- by the numbers ----------

def _numbers(ts: Styles, numbers: list[dict]) -> str:
    if not numbers:
        return ""
    width = f"{96 // len(numbers)}%"
    cells = []
    for i, n in enumerate(numbers):
        color = _topic(ts, n.get("topic")).color
        if i:
            cells.append('<td width="2%" style="font-size:0;">&nbsp;</td>')
        # styles sit on the cell so all tiles stretch to the same height
        cells.append(
            f'<td valign="top" width="{width}" style="background:{PANEL};border-radius:12px;'
            f'border-top:4px solid {color};padding:14px 12px 16px;">'
            f'<div style="font-size:26px;font-weight:800;letter-spacing:-.02em;line-height:1.1;color:{INK};">{e(n["value"])}</div>'
            f'<div style="font-size:12px;line-height:1.45;color:{MUTED};margin-top:6px;">{e(n["label"])}</div></td>')
    return (_section_head("By the numbers", ACCENT)
            + f'<tr><td style="padding:10px {PAD} 4px;"><table role="presentation" width="100%" cellpadding="0" '
            + f'cellspacing="0"><tr>{"".join(cells)}</tr></table></td></tr>')


# ---------- stories ----------

def _why(ts: Styles, s: dict) -> str:
    if not s.get("why_it_matters"):
        return ""
    _, color, tint, _ = _topic(ts, s["topic"])
    return (f'<div style="background:{tint};border-radius:10px;padding:12px 14px;margin:4px 0 0;">'
            f'<div style="font-size:11px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;color:{color};margin-bottom:4px;">Why it matters</div>'
            f'<div style="font-size:14px;line-height:1.6;color:{INK};">{e(s["why_it_matters"])}</div></div>')


def _term(s: dict) -> str:
    term = s.get("term")
    if not (isinstance(term, dict) and term.get("name")):
        return ""
    return (f'<table role="presentation" cellpadding="0" cellspacing="0" style="margin-top:10px;"><tr>'
            f'<td valign="top" style="padding:3px 8px;background:{INK};border-radius:6px;font-size:10px;font-weight:800;'
            f'letter-spacing:.08em;color:#ffffff;white-space:nowrap;">TERM</td>'
            f'<td style="padding-left:10px;font-size:13px;line-height:1.55;color:{MUTED};">'
            f'<b style="color:{INK};">{e(term["name"])}</b>: {e(term.get("meaning"))}</td></tr></table>')


def _meta(s: dict) -> str:
    return (f'<p style="margin:10px 0 0;font-size:12px;color:{MUTED};">{e(s["source"])} · '
            f'<a href="{e(s["url"])}" style="color:{MUTED};">original</a></p>')


def _story_big(ts: Styles, s: dict) -> str:
    img = ""
    if s.get("image"):
        img = (f'<img src="{e(s["image"])}" alt="" width="584" style="display:block;width:100%;max-width:584px;'
               f'height:auto;border-radius:12px;margin:0 0 14px;background:{PANEL};">')
    return f"""
<tr><td style="padding:16px {PAD} 22px;border-bottom:1px solid {LINE};">
  {img}
  <div style="margin-bottom:8px;">{_pill(ts, s["topic"])}</div>
  <div style="font-size:20px;font-weight:800;letter-spacing:-.01em;line-height:1.3;color:{INK};margin-bottom:10px;">{e(s["headline"])}</div>
  {_paras(s.get("summary"))}
  {_why(ts, s)}
  {_term(s)}
  {_meta(s)}
</td></tr>"""


def _story_small(ts: Styles, s: dict) -> str:
    thumb = ""
    if s.get("image"):
        thumb = (f'<td valign="top" width="96" style="padding-left:14px;">'
                 f'<img src="{e(s["image"])}" alt="" width="96" style="display:block;width:96px;height:auto;'
                 f'border-radius:10px;background:{PANEL};"></td>')
    return f"""
<tr><td style="padding:16px {PAD} 20px;border-bottom:1px solid {LINE};">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
    <td valign="top">
      <div style="font-size:17px;font-weight:700;line-height:1.35;color:{INK};margin-bottom:8px;">{e(s["headline"])}</div>
    </td>{thumb}
  </tr></table>
  {_paras(s.get("summary"), 15)}
  {_why(ts, s)}
  {_term(s)}
  {_meta(s)}
</td></tr>"""


def _quick_hits(ts: Styles, hits: list[dict]) -> str:
    if not hits:
        return ""
    rows = "".join(
        f'<tr><td valign="top" style="padding:10px 12px 10px 0;width:4px;">'
        f'<div style="width:4px;height:36px;border-radius:2px;background:{_topic(ts, q["topic"]).color};"></div></td>'
        f'<td style="padding:10px 0;border-bottom:1px solid {LINE};font-size:14px;line-height:1.55;color:{INK};">'
        f'{e(q["text"])} <a href="{e(q["url"])}" style="color:{MUTED};font-size:12px;white-space:nowrap;">{e(q["source"])}</a></td></tr>'
        for q in hits)
    return (_section_head("Quick hits", MUTED)
            + f'<tr><td style="padding:4px {PAD} 4px;"><table role="presentation" width="100%" cellpadding="0" '
            + f'cellspacing="0">{rows}</table></td></tr>')


# ---------- lesson visuals ----------

def _visual_flow(v: dict) -> str:
    steps = [s for s in v.get("steps", []) if isinstance(s, dict) and s.get("label")][:6]
    if len(steps) < 2:
        return ""
    rows = []
    for i, step in enumerate(steps, 1):
        detail = (f'<div style="font-size:13px;line-height:1.5;color:{MUTED};margin-top:2px;">{e(step["detail"])}</div>'
                  if step.get("detail") else "")
        weight = "700" if detail else "500"
        rows.append(
            f'<tr><td valign="top" width="30" style="width:30px;">'
            f'<div style="width:30px;height:30px;border-radius:15px;background:{ACCENT};color:#ffffff;font-size:13px;'
            f'font-weight:800;line-height:30px;text-align:center;">{i}</div></td>'
            f'<td valign="top" style="padding:0 0 0 12px;">'
            f'<div style="background:#ffffff;border:1px solid {LINE};border-radius:10px;padding:9px 12px;">'
            f'<div style="font-size:14px;line-height:1.5;font-weight:{weight};color:{INK};">{e(step["label"])}</div>'
            f'{detail}</div></td></tr>')
        if i < len(steps):
            rows.append(f'<tr><td align="center" style="font-size:14px;line-height:14px;color:{ACCENT};padding:4px 0;">&#9660;</td><td></td></tr>')
    return f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{"".join(rows)}</table>'


def _fmt_num(value: float, unit: str) -> str:
    text = f"{value:,.0f}" if abs(value) >= 100 or value == int(value) else f"{value:,.1f}"
    if unit in ("%", "x"):
        return f"{text}{unit}"
    if unit in ("₹", "$", "€", "£"):
        return f"{unit}{text}"
    return f"{text} {unit}".strip()


def _visual_bars(v: dict) -> str:
    items = []
    for item in v.get("items", []):
        try:
            value = float(item.get("value"))
        except (TypeError, ValueError, AttributeError):
            continue
        if value >= 0 and item.get("label"):
            items.append((str(item["label"]), value))
    items = items[:6]
    peak = max((val for _, val in items), default=0)
    if len(items) < 2 or peak <= 0:
        return ""
    unit = str(v.get("unit") or "").strip()
    rows = []
    for label, value in items:
        pct = max(1, round(value / peak * 78))  # leave room for the value label at the tip
        rows.append(
            f'<tr><td width="34%" style="padding:5px 10px 5px 0;font-size:13px;line-height:1.3;color:{MUTED};">{e(label)}</td>'
            f'<td style="padding:5px 0;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>'
            f'<td width="{pct}%" style="background:{ACCENT};height:18px;border-radius:0 4px 4px 0;font-size:0;line-height:0;">&nbsp;</td>'
            f'<td style="padding-left:8px;font-size:13px;font-weight:700;color:{INK};white-space:nowrap;">{e(_fmt_num(value, unit))}</td>'
            f'</tr></table></td></tr>')
    return f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{"".join(rows)}</table>'


def _visual_compare(v: dict) -> str:
    left, right = v.get("left") or {}, v.get("right") or {}
    if not (isinstance(left, dict) and isinstance(right, dict) and left.get("name") and right.get("name")):
        return ""

    def col(side: dict, color: str, pad: str) -> str:
        return (f'<td valign="top" width="50%" style="{pad}"><div style="background:#ffffff;border:1px solid {LINE};'
                f'border-top:4px solid {color};border-radius:10px;padding:12px 12px 4px;">'
                f'<div style="font-size:14px;font-weight:800;color:{INK};margin-bottom:8px;">{e(side["name"])}</div>'
                f'{_bullets(side.get("points", [])[:4], INK, 13)}</div></td>')

    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>'
            f'{col(left, ACCENT, "padding-right:6px;")}{col(right, "#0f766e", "padding-left:6px;")}</tr></table>')


def _visual(v) -> str:
    if not isinstance(v, dict):
        return ""
    body = {"flow": _visual_flow, "bars": _visual_bars, "compare": _visual_compare}.get(v.get("type"), lambda _: "")(v)
    if not body:
        return ""
    title = (f'<div style="font-size:13px;font-weight:700;color:{INK};margin-bottom:12px;">{e(v.get("title"))}</div>'
             if v.get("title") else "")
    return (f'<div style="background:#ffffff;border-radius:12px;padding:16px;margin:4px 0 16px;border:1px solid {LINE};">'
            f'{_kicker("Visual", ACCENT)}{title}{body}</div>')


def _progress(progress: list[dict], current: str) -> str:
    rows = []
    for p in progress:
        weight = "800" if p["key"] == current else "500"
        rows.append(
            f'<tr><td width="92" style="padding:3px 10px 3px 0;font-size:12px;font-weight:{weight};color:{INK};">{e(p["name"])}</td>'
            f'<td style="padding:3px 0;">{_meter(p["done"], p["total"])}</td>'
            f'<td width="48" align="right" style="padding:3px 0 3px 10px;font-size:12px;color:{MUTED};white-space:nowrap;">{p["done"]}/{p["total"]}</td></tr>')
    return f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{"".join(rows)}</table>' if rows else ""


def _lesson(lesson: dict, progress: list[dict]) -> str:
    track = lesson.get("track_name") or str(lesson.get("track", "")).title()
    body = [
        f'<div style="font-size:17px;line-height:1.5;color:{INK};font-weight:700;margin:0 0 14px;">{e(lesson.get("one_liner"))}</div>',
        _paras(lesson.get("explanation", [])),
        _visual(lesson.get("visual")),
        _label("Worked example"),
        _paras(lesson.get("example"), 14),
        _label("In the real world"),
        _paras(lesson.get("in_the_wild"), 14),
        _label("Common pitfalls", "#b91c1c"),
        _bullets(lesson.get("pitfalls", [])),
        f'<div style="background:{INK};border-radius:10px;padding:14px 16px;margin-top:6px;'
        f'font-size:14px;line-height:1.55;color:#ffffff;"><b style="color:#a5b4fc;">Remember:</b> {e(lesson.get("remember"))}</div>',
    ]
    return (_section_head(lesson.get("topic", ""), ACCENT, f"Learn · {track} · Lesson {lesson.get('number', 1)}")
            + f'<tr><td style="padding:12px {PAD} 4px;">'
            + f'<div style="background:{ACCENT_TINT};border-radius:14px;padding:18px 18px 16px;">'
            + (f'<div style="margin-bottom:16px;">{_progress(progress, lesson.get("track", ""))}</div>' if progress else "")
            + "".join(body) + "</div></td></tr>")


# ---------- challenge ----------

def _solution(prev: dict) -> str:
    sol = prev.get("solution") if isinstance(prev.get("solution"), dict) else {}
    recap = (f'<div style="background:{PANEL};border-radius:10px;padding:12px 14px;margin-bottom:4px;">'
             + _kicker("The question")
             + _paras(prev.get("scenario"), 14, MUTED)
             + f'<p style="margin:0;font-size:14px;line-height:1.6;color:{INK};"><b>Task:</b> {e(prev.get("task"))}</p></div>')
    return (_section_head(prev.get("title", ""), "#047857", f"{prev.get('when', 'Earlier challenge')} · Solution")
            + f'<tr><td style="padding:12px {PAD} 4px;"><div style="border:1px solid {LINE};border-radius:14px;padding:18px;">'
            + recap
            + _label("Approach") + _visual_flow({"steps": [{"label": step} for step in sol.get("approach", [])]})
            + _label("Sample answer") + _paras(sol.get("sample_answer"), 14)
            + '<div style="background:#e7f6f0;border-radius:10px;padding:12px 14px 2px;margin-bottom:10px;">'
            + _kicker("What good looks like", "#047857") + _bullets(sol.get("what_good_looks_like", []), INK, 13) + "</div>"
            + '<div style="background:#fdecec;border-radius:10px;padding:12px 14px 2px;">'
            + _kicker("Common mistakes", "#b91c1c") + _bullets(sol.get("common_mistakes", []), INK, 13) + "</div>"
            + "</div></td></tr>")


def _difficulty(level) -> str:
    try:
        level = max(1, min(3, int(level)))
    except (TypeError, ValueError):
        level = 2
    dots = "".join(f'<span style="color:{ACCENT if i < level else "#c7c2da"};">&#9679;</span>' for i in range(3))
    name = {1: "Warm-up", 2: "Solid", 3: "Stretch"}[level]
    return (f'<span style="font-size:15px;letter-spacing:2px;">{dots}</span> '
            f'<span style="font-size:12px;font-weight:700;color:{MUTED};">{name}</span>')


def _challenge(ch: dict) -> str:
    hints = "".join(f'<li style="margin:0 0 4px;">{e(h)}</li>' for h in ch.get("hints", []))
    return (_section_head(ch.get("title", ""), "#c2410c", "Today's challenge")
            + f'<tr><td style="padding:12px {PAD} 4px;"><div style="background:#fff8f3;border:2px dashed #f0b999;border-radius:14px;padding:18px 20px;">'
            + '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:12px;"><tr>'
            + f'<td style="font-size:12px;">{_difficulty(ch.get("difficulty"))}</td>'
            + '<td align="right"><span style="display:inline-block;background:#ffffff;border:1px solid #f0b999;border-radius:999px;'
            + 'padding:3px 10px;font-size:12px;font-weight:700;color:#c2410c;">~15 min</span></td></tr></table>'
            + _paras(ch.get("scenario"))
            + f'<div style="background:#ffffff;border-radius:10px;padding:12px 14px;font-size:15px;line-height:1.6;color:{INK};">'
            + f'<b>Your task:</b> {e(ch.get("task"))}</div>'
            + (_label("Hints, only if you're stuck")
               + f'<ul style="margin:0;padding-left:20px;font-size:13px;line-height:1.55;color:{MUTED};">{hints}</ul>' if hints else "")
            + f'<p style="margin:14px 0 0;font-size:12px;color:{MUTED};">Jot your answer down. The solution arrives in tomorrow\'s digest.</p>'
            + "</div></td></tr>")


# ---------- assembly ----------

def render_html(d: dict, t: Template) -> str:
    ts = topic_styles(t)
    rows = [_header(d, t, ts)]
    preheader = d["tldr"][0] if d.get("tldr") else "Your daily briefing"

    if d.get("fallback"):
        rows.append(f'<tr><td style="padding:16px {PAD} 0;font-size:13px;color:#b45309;">'
                    'The summarizer was unavailable today, so this is a headlines-only edition.</td></tr>')

    rows.append(_numbers(ts, d.get("numbers") or []))

    for section in d["sections"]:
        if not section["items"]:
            continue
        key = section["key"]
        rows.append(_section_head(_section_title(ts, key), INK if key == "top" else _topic(ts, key).color))
        rows.extend((_story_big if key == "top" else _story_small)(ts, s) for s in section["items"])

    rows.append(_quick_hits(ts, d.get("quick_hits") or []))

    if d.get("lesson"):
        rows.append(_lesson(d["lesson"], d.get("progress") or []))
    for sol in d.get("solutions") or []:
        rows.append(_solution(sol))
    if d.get("challenge"):
        rows.append(_challenge(d["challenge"]))

    st = d["stats"]
    rows.append(f'<tr><td style="padding:32px {PAD};font-size:12px;line-height:1.6;color:{MUTED};text-align:center;">'
                f'Read {st["candidates"]} fresh items from {st["sources_ok"]} of {st["sources_total"]} sources.<br>'
                f'{e(t.name)} · delivered at 7 AM IST</td></tr>')

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"><title>{e(t.name)}</title></head>
<body style="margin:0;padding:0;background:{PAGE};font-family:{FONT};">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;">{e(preheader)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{PAGE};">
<tr><td align="center" style="padding:20px 8px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:640px;background:#ffffff;border-radius:18px;overflow:hidden;font-family:{FONT};">
{"".join(rows)}
</table></td></tr></table></body></html>"""


def render_text(d: dict, t: Template) -> str:
    ts = topic_styles(t)
    out = [f"{t.name.upper()} · Issue #{d.get('issue', 1)} · {d['date_label']}", ""]
    if d.get("tldr"):
        out += ["TL;DR"] + [f"{i}. {t}" for i, t in enumerate(d["tldr"], 1)] + [""]
    if d.get("numbers"):
        out += ["BY THE NUMBERS"] + [f"- {n['value']}: {n['label']}" for n in d["numbers"]] + [""]
    for section in d["sections"]:
        if not section["items"]:
            continue
        out += [_section_title(ts, section["key"]).upper(), ""]
        for s in section["items"]:
            out += [f"[{_topic(ts, s['topic']).label}] {s['headline']}", s.get("summary") or ""]
            if s.get("why_it_matters"):
                out.append(f"Why it matters: {s['why_it_matters']}")
            out += [f"{s['source']}: {s['url']}", ""]
    if d.get("quick_hits"):
        out += ["QUICK HITS"] + [f"- {q['text']} ({q['source']})" for q in d["quick_hits"]] + [""]
    if d.get("lesson"):
        les = d["lesson"]
        out += [f"LEARN: {les.get('topic')}", les.get("one_liner", ""), *les.get("explanation", []),
                f"Example: {les.get('example', '')}", f"In the real world: {les.get('in_the_wild', '')}",
                *[f"- {p}" for p in les.get("pitfalls", [])], f"Remember: {les.get('remember', '')}", ""]
    for p in d.get("solutions") or []:
        sol = p.get("solution") if isinstance(p.get("solution"), dict) else {}
        out += [f"{p.get('when', 'Earlier challenge').upper()}, SOLVED: {p.get('title')}",
                f"Task: {p.get('task', '')}", *[f"- {x}" for x in sol.get("approach", [])],
                sol.get("sample_answer", ""), ""]
    if d.get("challenge"):
        c = d["challenge"]
        out += [f"TODAY'S CHALLENGE: {c.get('title')}", c.get("scenario", ""), f"Your task: {c.get('task', '')}",
                *[f"Hint: {h}" for h in c.get("hints", [])], ""]
    return "\n".join(out)
