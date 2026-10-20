"""Learning-track rotation. Track contents live in each template's JSON.

Tracks rotate day by day and each walks its lesson list in order. Once a list runs
out, the LLM picks the next advanced topic, avoiding what's been covered.
"""

from templates import Template, Track


def next_lesson(state: dict, template: Template) -> tuple[Track | None, str | None]:
    """Returns (track, topic) for today without mutating state. topic None means the LLM picks."""
    if not template.tracks:
        return None, None
    cur = state["curriculum"]
    track = template.tracks[cur["next"] % len(template.tracks)]
    idx = cur["positions"].get(track.key, 0)
    return track, track.lessons[idx] if idx < len(track.lessons) else None


def lesson_number(state: dict, track: Track) -> int:
    return state["curriculum"]["positions"].get(track.key, 0) + 1


def advance(state: dict, template: Template, track: Track, topic: str) -> None:
    cur = state["curriculum"]
    cur["positions"][track.key] = cur["positions"].get(track.key, 0) + 1
    cur["next"] = (template.tracks.index(track) + 1) % len(template.tracks)
    state["covered_concepts"].append(topic)


def challenge_type(template: Template, weekday: int) -> str:
    return template.challenge_types[weekday % len(template.challenge_types)]
