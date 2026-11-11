"""Render the ranked experiments as a Markdown game day plan or as JSON-ready data."""

from __future__ import annotations

from dataclasses import asdict

from .experiments import Experiment
from .inventory import Inventory
from .postmortems import Postmortem

NOTICE = ("This is a plan for people to review and run. gameday-planner does not inject failures "
          "and has not touched any system.")


def to_markdown(inv: Inventory, postmortems: list[Postmortem], experiments: list[Experiment],
                notes: list[str], top: int, title: str = "Game day plan") -> str:
    shown = experiments[:top]
    declared = [s for s in inv.services.values() if s.declared]
    edges = sum(len(s.depends_on) for s in declared)
    out = [
        f"# {title}", "",
        f"> {NOTICE}", "",
        f"Inputs: {len(declared)} services, {edges} dependencies, {len(postmortems)} postmortems. "
        f"{len(experiments)} candidate experiments were generated; the top {len(shown)} are below.", "",
        "## Ranked experiments", "",
        "Priority is risk covered divided by an effort factor (low 1, medium 1.5, high 2). Risk counts the "
        "most critical tier reached, downstream services, past incidents rehearsed and untested assumptions.", "",
        "| # | Experiment | Priority | Risk | Effort | Blast radius | Past incidents |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    out += [f"| {e.id} | {e.title} | {e.priority:g} | {e.risk:g} | {e.effort_label} | {e.blast_radius} | "
            f"{len(e.incidents)} |" for e in shown]
    out.append("")
    for e in shown:
        out += [
            f"## {e.id}. {e.title}", "",
            f"- **Type:** {e.kind}",
            f"- **Target:** {e.target}",
            f"- **Why now:** {'; '.join(e.reasons)}.",
        ]
        if e.incidents:
            out.append(f"- **Past incidents:** {'; '.join(e.incidents)}")
        out += [
            f"- **Hypothesis:** {e.hypothesis}",
            f"- **Method:** {e.method}",
            f"- **Blast radius:** {e.blast_radius}. If the hypothesis is wrong, impact could reach: "
            f"{', '.join(e.affected)}.",
            f"- **Where to run:** {e.environment}",
            "- **Abort if:**",
        ]
        out += [f"  - {a}" for a in e.abort_conditions]
        out += [f"- **Rollback:** {e.rollback}", ""]
    if notes:
        out += ["## Gaps and notes", ""] + [f"- {n}" for n in notes] + [""]
    out += [
        "## Before the game day", "",
        "- [ ] Each experiment has a named owner and the owning team has reviewed its hypothesis and abort conditions.",
        "- [ ] Dashboards and alerts for every service in the blast radius are open and known to work.",
        "- [ ] The rollback for each experiment has been rehearsed or at least read aloud.",
        "- [ ] On-call and support know the schedule; a single person has authority to stop everything.",
        "- [ ] Results (hypothesis held or not, surprises, follow-up actions) will be written down per experiment.", "",
    ]
    return "\n".join(out)


def to_dict(inv: Inventory, postmortems: list[Postmortem], experiments: list[Experiment],
            notes: list[str], top: int) -> dict:
    return {
        "notice": NOTICE,
        "services": len([s for s in inv.services.values() if s.declared]),
        "postmortems": [asdict(p) for p in postmortems],
        "candidates": len(experiments),
        "experiments": [{**asdict(e), "effort_label": e.effort_label} for e in experiments[:top]],
        "notes": notes,
    }
