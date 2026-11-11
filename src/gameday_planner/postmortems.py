"""Read past postmortems (Markdown or text) and extract what failed and how."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# Failure mode -> phrases that indicate it. Checked case-insensitively.
FAILURE_MODES: dict[str, tuple[str, ...]] = {
    "dependency-outage": ("outage", "unavailable", "unreachable", "was down", "went down", "returned 5", "hard down"),
    "latency": ("latency", "slow response", "slowdown", "timed out", "timeout", "timeouts", "degraded response"),
    "failover": ("failover", "fail over", "failed over", "promotion", "leader election", "split brain",
                 "replication lag"),
    "resource-exhaustion": ("disk full", "out of disk", "out of memory", "oom kill", "oom-kill", "oomkill", "connection pool", "exhaust",
                            "file descriptor", "cpu saturation", "memory leak"),
    "overload": ("traffic spike", "overload", "thundering herd", "retry storm", "backlog", "queue depth",
                 "rate limit"),
    "cache-loss": ("cold cache", "cache flush", "cache was flushed", "cache miss", "cache eviction", "cache stampede"),
    "instance-loss": ("node failure", "instance terminated", "pod evicted", "crash loop", "crashloop", "host died",
                      "instances were terminated"),
}
_CAUSE_SECTION = re.compile(r"^#+\s*(root cause|cause|trigger|what happened)[^\n]*\n(.*?)(?=^#+\s|\Z)", re.I | re.M | re.S)
_DATE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
_HEADING = re.compile(r"^\s*#\s+(.+?)\s*$", re.M)


@dataclass
class Postmortem:
    path: str
    title: str
    date: str = ""
    services: list[str] = field(default_factory=list)
    modes: list[str] = field(default_factory=list)


def _mentions(text: str, name: str) -> bool:
    # "orders-db" also matches "orders_db" and "orders db"; require word boundaries.
    pattern = r"(?<![\w-])" + r"[-_ ]".join(re.escape(part) for part in re.split(r"[-_ ]", name)) + r"(?![\w-])"
    return re.search(pattern, text, re.I) is not None


def _has_phrase(lowered: str, phrase: str) -> bool:
    # Match at a word start so "oom kill" is found but "headroom" does not match "oom".
    return re.search(r"(?<![a-z0-9])" + re.escape(phrase), lowered) is not None


def parse_postmortem(text: str, path: str, service_names: list[str]) -> Postmortem:
    heading = _HEADING.search(text)
    first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    title = heading.group(1) if heading else first_line or Path(path).stem
    date = _DATE.search(Path(path).name) or _DATE.search(text)
    lowered = text.lower()
    # Prefer the services named in the title or root-cause section: they are the ones
    # that failed. Services only mentioned in passing would otherwise inflate rankings.
    cause = _CAUSE_SECTION.search(text)
    focus_text = title + "\n" + (cause.group(2) if cause else "")
    focus = [n for n in service_names if _mentions(focus_text, n)]
    return Postmortem(
        path=path,
        title=title,
        date=date.group(1) if date else "",
        services=focus or [n for n in service_names if _mentions(text, n)],
        modes=[mode for mode, phrases in FAILURE_MODES.items() if any(_has_phrase(lowered, p) for p in phrases)],
    )


def load_postmortems(directory: str | Path, service_names: list[str]) -> list[Postmortem]:
    root = Path(directory)
    if not root.is_dir():
        raise NotADirectoryError(f"not a directory: {root}")
    files = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in (".md", ".markdown", ".txt"))
    return [parse_postmortem(p.read_text(encoding="utf-8", errors="replace"), str(p.relative_to(root)), service_names)
            for p in files]
