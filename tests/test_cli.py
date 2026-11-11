import json
from pathlib import Path

import gameday_planner
from gameday_planner.cli import main

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
ARGS = ["plan", "--services", str(EXAMPLES / "services.yaml"), "--postmortems", str(EXAMPLES / "postmortems")]


def test_plan_from_examples(capsys):
    assert main(ARGS) == 0
    out = capsys.readouterr().out
    assert out.startswith("# Game day plan\n\n> This is a plan for people to review and run.")
    assert "Inputs: 10 services, 11 dependencies, 4 postmortems. 32 candidate experiments" in out
    assert "| E1 | Flush product-cache (cold cache) | 7.5 | 7.5 | low | large | 1 |" in out
    assert "Catalog errors after product-cache was flushed (2026-01-20)" in out
    assert "## E8." in out and "## E9." not in out  # default --top 8
    assert "Fail over the primary of orders-db" in out
    assert "Office wifi outage" in out and "not used" in out
    assert "catalog-db has a single instance" in out
    assert "## Before the game day" in out


def test_top_title_and_no_postmortems(capsys):
    assert main(ARGS[:3] + ["--top", "2", "--title", "Q2 game day"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("# Q2 game day") and "0 postmortems" in out
    assert "## E2." in out and "## E3." not in out and "Past incidents:**" not in out


def test_json_output_and_file(tmp_path, capsys):
    target = tmp_path / "plan.json"
    assert main(ARGS + ["--format", "json", "--top", "3", "-o", str(target)]) == 0
    captured = capsys.readouterr()
    assert captured.out == "" and "Wrote 3 experiments" in captured.err
    data = json.loads(target.read_text())
    assert data["candidates"] == 32 and len(data["experiments"]) == 3 and len(data["postmortems"]) == 4
    first = data["experiments"][0]
    assert first["id"] == "E1" and first["effort_label"] == "low" and len(first["abort_conditions"]) == 4
    assert "does not inject failures" in data["notice"]


def test_errors_exit_2(tmp_path, capsys):
    assert main(["plan", "--services", str(tmp_path / "missing.yaml")]) == 2
    assert "cannot read" in capsys.readouterr().err
    assert main(ARGS[:3] + ["--postmortems", str(tmp_path / "nope")]) == 2
    assert "not a directory" in capsys.readouterr().err
    assert main(ARGS + ["--top", "0"]) == 2


def test_planning_only_no_process_or_network_modules():
    """The package must not be able to act on a system: no subprocess, sockets or HTTP clients."""
    forbidden = ("import subprocess", "import socket", "urllib", "http.client", "os.system", "import requests")
    for path in Path(gameday_planner.__file__).parent.glob("*.py"):
        source = path.read_text()
        assert not [word for word in forbidden if word in source], path.name
