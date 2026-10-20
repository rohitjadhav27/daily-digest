"""Daily Digest: for each template, fetch, select, summarize, teach, challenge, send.

Usage:
  python digest.py                      # build and send every enabled template due today
  python digest.py --template daily     # only this template
  python digest.py --dry-run            # write preview-<id>.html / .txt, no send, no state change
  python digest.py --force              # resend even if today's digest already went out
"""

import argparse
import os
import smtplib
import sys
import traceback
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from zoneinfo import ZoneInfo

import compose
import curriculum
import llm
import state as state_store
from fetch import Article, collect_candidates, load_full_text, normalize_url
from render import render_html, render_text
from templates import Template, TemplateError, load_all

NOW = datetime.now(ZoneInfo("Asia/Kolkata"))
TODAY = NOW.date()
MAX_REVEALS = 3


def story_view(a: Article, written: dict | None) -> dict:
    w = written or {}
    return {
        "topic": a.topic,
        "source": a.source,
        "url": a.url,
        "headline": w.get("headline") or a.title,
        "summary": w.get("summary") or compose._clip(a.teaser, 400),
        "why_it_matters": w.get("why_it_matters", ""),
        "term": w.get("term"),
        "image": a.image,
    }


def clean_numbers(raw, by_id: dict[str, Article]) -> list[dict]:
    numbers = []
    for n in raw if isinstance(raw, list) else []:
        if isinstance(n, dict) and n.get("value") and n.get("label"):
            article = by_id.get(n.get("id"))
            numbers.append({"value": str(n["value"])[:10], "label": str(n["label"]),
                            "topic": article.topic if article else ""})
    return numbers[:3]


def build_news_with_llm(t: Template, candidates: list[Article]):
    by_id = {a.id: a for a in candidates}
    selection = compose.select_stories(t, candidates)
    story_ids = [i for key in compose.section_keys(t) for i in selection[key]]
    if not story_ids:
        raise llm.LLMError("selection came back empty")

    stories = [by_id[i] for i in story_ids]
    hits = [by_id[i] for i in selection["quick_hits"]]
    load_full_text(stories)
    written = compose.strip_em_dashes(compose.write_stories(t, stories, hits))
    w_stories = written.get("stories") if isinstance(written.get("stories"), dict) else {}
    w_hits = written.get("quick_hits") if isinstance(written.get("quick_hits"), dict) else {}

    sections = [{"key": key, "items": [story_view(by_id[i], w_stories.get(i)) for i in selection[key]]}
                for key in compose.section_keys(t)]
    quick = [{"topic": a.topic, "source": a.source, "url": a.url, "text": w_hits.get(a.id) or a.title} for a in hits]
    tldr = [x for x in written.get("tldr") or [] if isinstance(x, str)][:3]
    return tldr, clean_numbers(written.get("numbers"), by_id), sections, quick, stories + hits


def build_news_fallback(t: Template, candidates: list[Article]):
    """Headlines-only edition: 3 newest per topic, no LLM."""
    sections, used = [], []
    for key in t.topics:
        picks = [a for a in candidates if a.topic == key][:3]
        used += picks
        sections.append({"key": key, "items": [story_view(a, None) for a in picks]})
    return [], [], sections, [], used


def build_learning(t: Template, state: dict, headlines: list[str]) -> tuple[dict | None, dict | None]:
    """Returns (lesson, challenge) freshly generated for today. Either may be None."""
    track, topic = curriculum.next_lesson(state, t)
    try:
        raw = compose.strip_em_dashes(compose.write_lesson_and_challenge(
            t, track.name if track else None, topic, state["covered_concepts"],
            curriculum.challenge_type(t, TODAY.weekday()), state["challenge_history"], headlines))
    except llm.LLMError as e:
        print(f"  Lesson/challenge failed: {e}")
        return None, None

    lesson = raw.get("lesson") if track and isinstance(raw.get("lesson"), dict) else None
    challenge = raw.get("challenge") if isinstance(raw.get("challenge"), dict) else None
    if lesson:
        lesson.setdefault("topic", topic or "Today's lesson")
        lesson["track"] = track.key
        lesson["track_name"] = track.name
        lesson["number"] = curriculum.lesson_number(state, track)
    if challenge and not isinstance(challenge.get("solution"), dict):
        challenge = None
    return lesson, challenge


def send_email(t: Template, subject: str, html_body: str, text_body: str) -> list[str]:
    """Sends one message per recipient over a single connection. Returns recipients that failed."""
    sender = os.environ["SENDER_EMAIL"]
    password = os.environ["SENDER_APP_PASSWORD"].replace(" ", "").replace("\xa0", "").strip()
    failed: list[str] = []
    # Login errors propagate: nothing has been sent yet, so the whole template fails cleanly
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=60) as server:
        server.starttls()
        server.login(sender, password)
        # Log recipient numbers, never addresses: Actions logs are public on a public repo
        for n, rcpt in enumerate(t.recipients, 1):
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = formataddr((t.name, sender))
            msg["To"] = rcpt
            msg.attach(MIMEText(text_body, "plain", "utf-8"))
            msg.attach(MIMEText(html_body, "html", "utf-8"))
            try:
                server.sendmail(sender, [rcpt], msg.as_string())
            except smtplib.SMTPServerDisconnected as e:
                # Connection is gone: everyone left is undelivered, but earlier sends still count
                print(f"  ! Connection lost at recipient #{n}: {type(e).__name__}")
                failed.extend(t.recipients[t.recipients.index(rcpt):])
                break
            except smtplib.SMTPException as e:
                print(f"  ! Could not send to recipient #{n}: {type(e).__name__}")
                failed.append(rcpt)
            except OSError as e:
                # Socket timeout or reset (SMTPException subclasses OSError, so this must come after it)
                print(f"  ! Connection error at recipient #{n}: {type(e).__name__}")
                failed.extend(t.recipients[t.recipients.index(rcpt):])
                break
    return failed


def read_minutes(text: str) -> int:
    return max(3, round(len(text.split()) / 220))


def run_template(t: Template, dry_run: bool, force: bool) -> bool:
    """Builds and sends one template. Returns False if something needs attention."""
    print(f"\n== {t.name} ({t.id}) ==")
    state = state_store.load(t.id, [tr.key for tr in t.tracks])
    today = TODAY.isoformat()
    already_sent = state.get("last_sent") == today

    if not dry_run and not force:
        if already_sent:
            print("  Already sent today, skipping")
            return True
        if not t.sends_on(TODAY.weekday()):
            print(f"  Not scheduled on {TODAY:%A}, skipping")
            return True

    candidates, errors = collect_candidates(t.sources, set(state["sent_urls"]))
    print(f"  {len(candidates)} candidates from {len(t.sources) - len(errors)}/{len(t.sources)} sources")
    for name, err in errors.items():
        print(f"  ! {name}: {err}")

    fallback = not llm.available()
    if fallback:
        print("  No LLM key configured, sending headlines-only edition")
    else:
        try:
            tldr, numbers, sections, quick, used = build_news_with_llm(t, candidates)
        except llm.LLMError as e:
            print(f"  News LLM failed, falling back: {e}")
            fallback = True
    if fallback:
        tldr, numbers, sections, quick, used = build_news_fallback(t, candidates)

    # A resend on the same day reuses the day's lesson and challenge instead of replacing them.
    # If the first send got neither (LLM outage), a resend tries to generate them again.
    cached = state.get("today") if isinstance(state.get("today"), dict) else {}
    cached_lesson = cached.get("lesson") if cached.get("date") == today else None
    cached_challenge = next((c for c in reversed(state["challenges"]) if c.get("date") == today), None)
    reuse = bool(cached_lesson or cached_challenge)
    if reuse:
        lesson, challenge = cached_lesson, cached_challenge
    elif llm.available():
        headlines = [s["headline"] for sec in sections for s in sec["items"]]
        lesson, challenge = build_learning(t, state, headlines)
    else:
        lesson = challenge = None

    # Every earlier challenge not yet answered gets its solution now, so a skipped day loses nothing.
    # A backlog drains MAX_REVEALS at a time; solutions already shown today reappear on a resend.
    shown_today = [c for c in state["challenges"] if c.get("revealed_on") == today]
    unrevealed = [c for c in state["challenges"] if c.get("date", "") < today and not c.get("revealed")]
    to_reveal = unrevealed[-max(MAX_REVEALS - len(shown_today), 0):] if len(shown_today) < MAX_REVEALS else []
    reveals = shown_today + to_reveal

    positions = state["curriculum"]["positions"]
    progress = [{"key": tr.key, "name": tr.name,
                 "done": min(positions.get(tr.key, 0) + (1 if lesson and not reuse and lesson["track"] == tr.key else 0),
                             len(tr.lessons)),
                 "total": len(tr.lessons)}
                for tr in t.tracks if tr.lessons]
    issue = state.get("issue", 0) + (0 if already_sent else 1)

    digest = {
        "date_label": NOW.strftime("%A, %d %B %Y"),
        "issue": issue,
        "tldr": tldr,
        "numbers": numbers,
        "progress": progress,
        "sections": sections,
        "quick_hits": quick,
        "lesson": lesson,
        "solutions": [dict(c, when=_when(c.get("date", ""))) for c in reveals],
        "challenge": challenge,
        "fallback": fallback,
        "stats": {"candidates": len(candidates), "sources_ok": len(t.sources) - len(errors),
                  "sources_total": len(t.sources)},
        "read_minutes": 0,
    }
    digest["read_minutes"] = read_minutes(render_text(digest, t))
    text = render_text(digest, t)
    html = render_html(digest, t)

    lead = next((s["headline"] for sec in sections for s in sec["items"]), "Your daily briefing")
    subject = f"{NOW.strftime('%d %b')}: {compose._clip(lead, 80)}"

    if dry_run:
        for ext, body in (("html", html), ("txt", text)):
            with open(f"preview-{t.id}.{ext}", "w") as f:
                f.write(body)
        print(f"  Dry run. Subject: {subject}\n  Wrote preview-{t.id}.html and preview-{t.id}.txt")
        return True

    if not t.recipients:
        hint = f"set the {t.recipients_env} secret" if t.recipients_env else 'add "recipients" to the template'
        print(f"  ! No recipients configured ({hint}), nothing sent")
        return False
    failed = send_email(t, subject, html, text)
    if len(failed) == len(t.recipients):
        raise RuntimeError("no recipient could be reached, nothing was delivered")
    print(f"  Sent to {len(t.recipients) - len(failed)}/{len(t.recipients)}: {subject}")

    state["last_sent"] = today
    state["issue"] = issue
    for a in used:
        state["sent_urls"][normalize_url(a.url)] = today
    for c in to_reveal:
        c["revealed"] = True
        c["revealed_on"] = today
    if not reuse:
        if lesson:
            track = next(tr for tr in t.tracks if tr.key == lesson["track"])
            curriculum.advance(state, t, track, lesson["topic"])
        if challenge:
            state["challenges"].append(dict(challenge, date=today, revealed=False))
            state["challenge_history"].append(challenge.get("title", ""))
        state["today"] = {"date": today, "lesson": lesson}
    state_store.save(t.id, state, TODAY)
    return not failed


def _when(date_str: str) -> str:
    if date_str == (TODAY - timedelta(days=1)).isoformat():
        return "Yesterday's challenge"
    try:
        return f"Challenge from {datetime.fromisoformat(date_str):%a %d %b}"
    except ValueError:
        return "Earlier challenge"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="write preview files instead of sending")
    parser.add_argument("--force", action="store_true", help="send even if already sent today or not scheduled")
    parser.add_argument("--template", help="only run this template id")
    args = parser.parse_args()

    try:
        templates = load_all()
    except TemplateError as e:
        print(f"Template config error: {e}")
        return 1
    if args.template:
        templates = [t for t in templates if t.id == args.template]
        if not templates:
            print(f"No template named {args.template!r}")
            return 1
    else:
        templates = [t for t in templates if t.enabled]

    print(f"Daily Digest for {TODAY}: {', '.join(t.id for t in templates)}")
    ok = True
    for t in templates:
        try:
            ok = run_template(t, args.dry_run, args.force) and ok
        except Exception:
            # One broken template must not stop the others from sending
            traceback.print_exc()
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
