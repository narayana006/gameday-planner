"""Command-line interface for gameday-planner."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .experiments import coverage_notes, generate
from .inventory import InventoryError, load_inventory
from .postmortems import load_postmortems
from .render import to_dict, to_markdown


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gameday-planner",
        description="Propose and rank game day experiments. Planning only: it never injects failures.",
    )
    p.add_argument("--version", action="version", version=f"gameday-planner {__version__}")
    sub = p.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan", help="generate a ranked game day plan")
    plan.add_argument("--services", required=True, metavar="FILE", help="service inventory (YAML or JSON)")
    plan.add_argument("--postmortems", metavar="DIR", help="directory of past postmortems (.md, .markdown, .txt)")
    plan.add_argument("--top", type=int, default=8, metavar="N", help="number of experiments to include (default 8)")
    plan.add_argument("--format", choices=["markdown", "json"], default="markdown")
    plan.add_argument("--title", default="Game day plan")
    plan.add_argument("--output", "-o", metavar="FILE", help="write the plan to a file instead of stdout")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.top < 1:
        print("gameday-planner: --top must be at least 1", file=sys.stderr)
        return 2
    try:
        inventory = load_inventory(args.services)
        postmortems = load_postmortems(args.postmortems, list(inventory.services)) if args.postmortems else []
    except (InventoryError, NotADirectoryError) as exc:
        print(f"gameday-planner: {exc}", file=sys.stderr)
        return 2
    experiments = generate(inventory, postmortems)
    notes = coverage_notes(inventory, postmortems)
    if args.format == "json":
        text = json.dumps(to_dict(inventory, postmortems, experiments, notes, args.top), indent=2) + "\n"
    else:
        text = to_markdown(inventory, postmortems, experiments, notes, args.top, title=args.title)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"Wrote {min(args.top, len(experiments))} experiments to {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
