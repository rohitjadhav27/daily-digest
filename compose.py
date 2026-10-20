"""Prompts and LLM orchestration: select stories, write summaries, write the lesson and challenge."""

import json
import re

import llm
from fetch import Article
from templates import Template

STYLE = (
    "Write in plain, direct English like a sharp colleague. Use concrete facts, names and numbers "
    "from the source. No hype, no filler phrases, no em dashes. Define jargon in simple words."
)


def reader(t: Template) -> str:
    return (f"The reader is {t.audience}. They read this email instead of visiting websites, "
            "so everything must be understandable without clicking through.")


def section_keys(t: Template) -> list[str]:
    return ["top", *t.topics]


def _clip(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1].rsplit(" ", 1)[0] + "…"


def select_stories(t: Template, candidates: list[Article]) -> dict[str, list[str]]:
    topic_lines = "\n".join(
        f'- "{k}" ({topic.label}): up to 2 more stories (0 if nothing is worth it)'
        + (f"; favour {topic.focus}" if topic.focus else "")
        for k, topic in t.topics.items())
    shape = json.dumps({k: ["ids"] for k in [*section_keys(t), "quick_hits"]})
    system = f"""You are the editor of a daily briefing. {reader(t)}

From the candidate list, pick:
- "top": the 3 most significant stories of the day across all topics
{topic_lines}
- "quick_hits": 6 other notable items worth one line each

Rules:
- Each id appears at most once across all sections.
- Prefer substance: launches, research results, data, regulation, deals, deep analysis. Skip listicles,
  sponsored posts, podcast episode ads, minor funding rounds and clickbait.
- If several candidates cover the same event, pick the one from the most informative source.

Return JSON shaped like: {shape}"""

    def build(max_chars: int) -> str:
        teaser_len = 220 if max_chars > 60_000 else 70
        lines, used = [], 0
        for a in candidates:
            line = f"{a.id} | {a.topic} | {a.source} | {a.title} | {_clip(a.teaser, teaser_len)}"
            if used + len(line) > max_chars - 4000:
                break
            lines.append(line)
            used += len(line) + 1
        return "Candidates (id | topic | source | title | teaser):\n" + "\n".join(lines)

    raw = llm.json_call(system, build)
    valid = {a.id for a in candidates}
    picked: set[str] = set()
    selection: dict[str, list[str]] = {}
    for key in [*section_keys(t), "quick_hits"]:
        ids = raw.get(key) if isinstance(raw.get(key), list) else []
        ids = [i for i in ids if isinstance(i, str) and i in valid and i not in picked]
        picked.update(ids)
        selection[key] = ids
    return selection


def write_stories(t: Template, stories: list[Article], quick_hits: list[Article]) -> dict:
    system = f"""You write a daily briefing. {reader(t)} {STYLE}

For each story, write:
- "headline": clear and specific, max 14 words, no clickbait
- "summary": 3 to 4 sentences on what happened, with key facts and numbers
- "why_it_matters": 1 to 2 sentences on the practical implication for this reader
- "term": one piece of jargon from the story worth learning, as {{"name": "...", "meaning": "one plain sentence"}}, or null

For each quick hit, write one sentence (max 25 words) that stands on its own.
Also write "tldr": the 3 things that matter most today, one sentence each.
Also pick "numbers": the 3 most striking figures from today's stories, as
{{"value": "short figure, max 8 characters, e.g. $4.2B, 41%, 9x, ₹1,800", "label": "what it measures, max 8 words", "id": "<story id>"}}.
Only use figures stated in the source text. Return fewer if the stories have no hard numbers.

Return JSON: {{"tldr": [..3], "numbers": [..3], "stories": {{"<id>": {{"headline","summary","why_it_matters","term"}}}}, "quick_hits": {{"<id>": "sentence"}}}}"""

    def build(max_chars: int) -> str:
        per_story = max(600, min(6000, (max_chars - 6000) // max(len(stories), 1)))
        parts = ["STORIES:"]
        for a in stories:
            parts.append(f"\n[{a.id}] {a.title} ({a.source})\n{_clip(a.full_text or a.teaser, per_story)}")
        parts.append("\nQUICK HITS:")
        for a in quick_hits:
            parts.append(f"[{a.id}] {a.title} ({a.source}): {_clip(a.teaser, 200)}")
        return "\n".join(parts)

    return llm.json_call(system, build)


LESSON_SPEC = """Part 1, "lesson":
- "topic": the topic title
- "one_liner": the concept in one sentence a smart 15-year-old would get
- "explanation": 3 short paragraphs (list of strings): how it works, why it exists, the key tradeoffs
- "example": one concrete worked example with realistic numbers or a step-by-step walk-through
- "in_the_wild": 2 sentences on how it shows up in the real world; tie it to one of today's headlines if natural
- "pitfalls": 2 to 3 common misunderstandings or mistakes
- "remember": one sentence to remember it by
- "visual": ONE diagram that makes the concept click, in whichever of these shapes fits best:
  {"type": "flow", "title": "...", "steps": [{"label": "max 5 words", "detail": "max 15 words"}, ..3 to 5]}
    for processes, sequences, pipelines, lifecycles
  {"type": "bars", "title": "...", "unit": "%, ms, ₹ etc or empty", "items": [{"label": "max 4 words", "value": number}, ..3 to 6]}
    for quantities, e.g. the numbers from your worked example; values must be non-negative
  {"type": "compare", "title": "...", "left": {"name": "...", "points": [..3]}, "right": {"name": "...", "points": [..3]}}
    for X vs Y concepts and tradeoffs; points max 8 words each
"""


def write_lesson_and_challenge(t: Template, track_name: str | None, topic: str | None, covered: list[str],
                               challenge_type: str, recent_challenges: list[str], headlines: list[str]) -> dict:
    """With track_name None, only a challenge is written."""
    with_lesson = track_name is not None
    challenge_spec = f"""Part {2 if with_lesson else 1}, "challenge": a small exercise the reader can solve in about 15 minutes, answered in tomorrow's email.
Format: {challenge_type}. Make it specific, with a named (fictional) company or person and concrete numbers.
If natural, connect it to {"today's lesson or " if with_lesson else ""}headlines. It must differ from recent challenges.
- "title", "scenario" (2 to 4 sentences), "task" (exactly what to produce), "hints" (2 short hints),
  "difficulty" (1 = warm-up, 2 = solid, 3 = stretch; mostly 2)
- "solution": {{"approach": [3 to 5 steps], "sample_answer": "a strong answer in 120 to 200 words",
  "what_good_looks_like": [2 to 3 points], "common_mistakes": [2 points]}}"""

    system = f"""You are a teacher writing the learning section of a daily email. {reader(t)} {STYLE}

{f"Goal: {t.learning_goal}." if with_lesson else ""}

{LESSON_SPEC if with_lesson else ""}
{challenge_spec}

Return JSON: {'{"lesson": {...}, "challenge": {...}}' if with_lesson else '{"challenge": {...}}'}"""

    lines = []
    if with_lesson:
        lines.append(f'Today\'s lesson topic ({track_name} track): "{topic}"' if topic else
                     f"Pick the next most useful intermediate-to-advanced {track_name} topic that builds on what was covered.")
        lines.append("Already covered (do not repeat): " + ("; ".join(covered[-60:]) or "none"))
    if recent_challenges:
        lines.append("Recent challenges (avoid): " + "; ".join(recent_challenges[-20:]))
    lines.append("Today's headlines:\n- " + "\n- ".join(headlines[:15]))
    user = "\n".join(lines)

    return llm.json_call(system, lambda max_chars: user[:max_chars])


def strip_em_dashes(obj):
    """House style: no em dashes anywhere in the email."""
    if isinstance(obj, str):
        return re.sub(r"\s*—\s*", " - ", obj)
    if isinstance(obj, list):
        return [strip_em_dashes(x) for x in obj]
    if isinstance(obj, dict):
        return {k: strip_em_dashes(v) for k, v in obj.items()}
    return obj
