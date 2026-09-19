"""Demo CLI: ``python -m gooddeed_agent``.

Exercises all four agent functions and prints the exact JSON the backend will
receive. Runs against stub data when no API keys are set, so it is also the
fastest way to check whether your keys are actually wired up -- the header
says which providers are live.
"""

from __future__ import annotations

import argparse
import json
import sys

from . import classify_report, find_opportunities, score_submission, tier_for_points, trust_check
from .config import load_settings


def _dump(label: str, payload: object) -> None:
    print(f"\n--- {label} " + "-" * max(0, 60 - len(label)))
    print(json.dumps(payload, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gooddeed_agent", description=__doc__)
    parser.add_argument("--lat", type=float, default=39.2904, help="Latitude (default: Baltimore)")
    parser.add_argument("--lng", type=float, default=-76.6122, help="Longitude")
    parser.add_argument("--radius-km", type=float, default=5.0)
    parser.add_argument("--photo", help="Path or URL to a photo for the scoring demo")
    parser.add_argument(
        "--verify", action="store_true", help="Run real web-search trust checks (costs tokens)"
    )
    args = parser.parse_args(argv)

    settings = load_settings()
    print("GoodDeed Go agent demo")
    print(f"  model:  {settings.model}")
    print(f"  places: {'MOCK' if settings.use_mock_places else 'Google Places (live)'}")
    print(f"  llm:    {'MOCK' if settings.use_mock_llm else 'OpenAI (live)'}")

    opportunities = find_opportunities(
        args.lat, args.lng, args.radius_km, max_results=5, verify=args.verify
    )
    _dump("find_opportunities", opportunities)

    if opportunities:
        top = opportunities[0]
        _dump("trust_check", trust_check(top["org_name"], top["address"]))
    else:
        top = {"org_name": "Riverside Community Food Bank", "category": "food_bank"}

    if args.photo:
        score = score_submission(
            args.photo,
            "Sorted canned goods into family boxes with two other volunteers all morning.",
            top["org_name"],
            90,
            category=top.get("category"),
            include_debug=True,
        )
        _dump("score_submission", score)
        _dump(
            "tier after this submission",
            {"tier_points": score["tier_points"], "tier": tier_for_points(score["tier_points"])},
        )
        _dump(
            "classify_report",
            classify_report(args.photo, "Overflowing trash bins at the corner of 3rd and Maple"),
        )
    else:
        print("\n(pass --photo <path-or-url> to also demo score_submission and classify_report)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
