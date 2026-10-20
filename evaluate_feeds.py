"""Feed health check across every template: which sources work and how much fresh content each has."""

import sys

from fetch import fetch_sources
from templates import TemplateError, load_all


def main() -> int:
    try:
        templates = load_all()
    except TemplateError as e:
        print(f"Template config error: {e}")
        return 1

    for t in templates:
        print(f"\n== {t.name} ({t.id}){'' if t.enabled else ' [disabled]'} ==")
        print(f"{'SOURCE':<26} {'TOPIC':<10} {'FRESH':>5}  LATEST / ERROR")
        results = fetch_sources(t.sources)
        for src, items, err in results:
            if err:
                print(f"{src.name:<26} {src.topic:<10} {'FAIL':>5}  {err}")
                continue
            latest = items[0]["title"][:60] if items else "(nothing in window)"
            print(f"{src.name:<26} {src.topic:<10} {len(items):>5}  {latest}")
        failed = sum(1 for _, _, err in results if err)
        print(f"{len(results) - failed}/{len(results)} sources OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
