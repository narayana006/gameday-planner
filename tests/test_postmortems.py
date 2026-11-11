import pytest

from gameday_planner.postmortems import load_postmortems, parse_postmortem

NAMES = ["checkout-api", "orders-db", "api", "product-cache"]


def test_title_date_services_and_modes():
    text = ("# Database failover took too long\n\nDate: 2025-11-02\n\n"
            "The orders_db primary died and failover was slow. Checkout-API returned errors.\n")
    pm = parse_postmortem(text, "pm.md", NAMES)
    assert pm.title == "Database failover took too long" and pm.date == "2025-11-02"
    assert pm.services == ["checkout-api", "orders-db"]  # "api" alone is not matched inside checkout-api
    assert pm.modes == ["failover"]


def test_services_in_title_or_root_cause_take_precedence():
    text = ("# Slow checkout\n\n## Summary\n\nproduct-cache and orders-db were both mentioned.\n\n"
            "## Root cause\n\nNo timeout in checkout-api.\n\n## Action items\n\n- Review orders-db alerts.\n")
    assert parse_postmortem(text, "pm.md", NAMES).services == ["checkout-api"]


def test_date_from_filename_wins_and_title_falls_back():
    pm = parse_postmortem("no heading here\nDate: 2024-01-01\n", "2025-03-04-thing.md", NAMES)
    assert pm.date == "2025-03-04" and pm.title == "no heading here"
    assert parse_postmortem("", "empty-file.md", NAMES).title == "empty-file"


@pytest.mark.parametrize("text,mode", [
    ("requests timed out for an hour", "latency"),
    ("the provider was unavailable", "dependency-outage"),
    ("the volume hit disk full", "resource-exhaustion"),
    ("thread exhaustion in the pool", "resource-exhaustion"),
    ("pods were OOM killed", "resource-exhaustion"),
    ("a retry storm followed", "overload"),
    ("we served from a cold cache", "cache-loss"),
    ("the pod went into a crash loop", "instance-loss"),
])
def test_failure_mode_phrases(text, mode):
    assert mode in parse_postmortem(text, "x.md", NAMES).modes


def test_phrases_match_at_word_start_only():
    assert parse_postmortem("no capacity headroom, zoom call held", "x.md", NAMES).modes == []


def test_load_directory_reads_markdown_and_text_sorted(tmp_path):
    (tmp_path / "b.md").write_text("# B\napi was unavailable\n")
    (tmp_path / "a.txt").write_text("A incident\n")
    (tmp_path / "notes.pdf").write_text("ignored")
    sub = tmp_path / "2025"
    sub.mkdir()
    (sub / "c.md").write_text("# C\n")
    pms = load_postmortems(tmp_path, NAMES)
    assert [p.path for p in pms] == ["2025/c.md", "a.txt", "b.md"]
    assert pms[2].services == ["api"]
    with pytest.raises(NotADirectoryError):
        load_postmortems(tmp_path / "missing", NAMES)
