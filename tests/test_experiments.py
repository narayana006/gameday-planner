from gameday_planner.experiments import coverage_notes, generate
from gameday_planner.inventory import parse_inventory
from gameday_planner.postmortems import Postmortem

INV = {"services": [
    {"name": "web", "tier": 1, "replicas": 3, "depends_on": ["api", {"name": "recs", "critical": False}]},
    {"name": "api", "tier": 1, "replicas": 2,
     "depends_on": ["db", {"name": "cache", "fallback": True}, "pay-provider"]},
    {"name": "recs", "tier": 3, "replicas": 1},
    {"name": "db", "type": "database", "tier": 1, "replicas": 2},
    {"name": "cache", "type": "cache", "tier": 2},
    {"name": "jobs", "type": "queue", "tier": 3},
    {"name": "solo-db", "type": "database", "tier": 3, "replicas": 1},
]}


def plan(postmortems=()):
    inv = parse_inventory(INV)
    return inv, generate(inv, list(postmortems))


def by_title(experiments, title):
    return next(e for e in experiments if e.title == title)


def test_each_component_gets_the_experiments_that_fit_it():
    _, exps = plan()
    kinds = {}
    for e in exps:
        kinds.setdefault(e.kind, []).append(e.target)
    assert sorted(kinds["instance-loss"]) == ["api", "recs", "web"]  # plain services only
    assert kinds["failover"] == ["db"]  # solo-db has no replica to fail over to
    assert kinds["cache-loss"] == ["cache"] and kinds["queue-backlog"] == ["jobs"]
    edges = ["api -> cache", "api -> db", "api -> pay-provider", "web -> api", "web -> recs"]
    assert sorted(kinds["dependency-outage"]) == edges and sorted(kinds["dependency-latency"]) == edges
    assert "resource-exhaustion" not in kinds  # only proposed when history calls for it
    assert all(e.target != "pay-provider" for e in exps)  # never inject into a third party


def test_every_experiment_is_complete_and_ids_follow_rank():
    _, exps = plan()
    assert [e.id for e in exps] == [f"E{i}" for i in range(1, len(exps) + 1)]
    assert [e.priority for e in exps] == sorted((e.priority for e in exps), reverse=True)
    for e in exps:
        assert e.hypothesis and e.method and e.rollback and e.environment and e.reasons
        assert len(e.abort_conditions) == 4 and e.affected
        assert e.blast_radius in ("small", "medium", "large")


def test_hypothesis_depends_on_fallback_and_criticality():
    _, exps = plan()
    assert "fails fast" in by_title(exps, "Block api from reaching db").hypothesis
    assert "fallback" in by_title(exps, "Block api from reaching cache").hypothesis
    assert "optional" in by_title(exps, "Block web from reaching recs").hypothesis
    assert "single instance" in by_title(exps, "Terminate one instance of recs").hypothesis
    assert "remaining instances" in by_title(exps, "Terminate one instance of api").hypothesis


def test_blast_radius_follows_dependents_and_tier():
    _, exps = plan()
    failover = by_title(exps, "Fail over the primary of db")
    assert failover.affected == ["db", "api", "web"] and failover.blast_radius == "large"
    assert "Staging first" in failover.environment
    assert "more than 2 minutes" in failover.abort_conditions[0] and "db, api, web" in failover.abort_conditions[0]
    edge = by_title(exps, "Block api from reaching db")
    assert edge.affected == ["api", "web"] and edge.blast_radius == "medium"  # db itself is untouched
    backlog = by_title(exps, "Pause consumers of jobs to build a backlog")
    assert backlog.affected == ["jobs"] and backlog.blast_radius == "small"
    assert backlog.abort_conditions[0].startswith("Error rate or latency on jobs")


def test_scores_are_explained_and_reproducible():
    _, exps = plan()
    edge = by_title(exps, "Block api from reaching db")
    # tier 1 (3.0) + one downstream service (0.5) + hard dependency (1.0), medium effort (factor 1.5)
    assert (edge.risk, edge.effort, edge.priority) == (4.5, 2, 3.0)
    assert edge.reasons == ["reaches a tier 1 service", "1 downstream service could be affected",
                            "hard dependency with no fallback"]
    backlog = by_title(exps, "Pause consumers of jobs to build a backlog")
    assert (backlog.risk, backlog.priority) == (1.0, 0.67)


def test_past_incidents_raise_matching_experiments_only():
    pm = Postmortem("a.md", "DB failover stuck", "2025-11-02", services=["db"], modes=["failover", "latency"])
    _, before = plan()
    _, after = plan([pm])
    title = "Fail over the primary of db"
    assert by_title(after, title).risk == by_title(before, title).risk + 3.0
    assert by_title(after, title).incidents == ["DB failover stuck (2025-11-02)"]
    assert "rehearses 1 past incident" in by_title(after, title).reasons
    assert int(by_title(after, title).id[1:]) < int(by_title(before, title).id[1:])
    assert by_title(after, "Add latency between api and db").incidents  # latency to db matched too
    assert by_title(after, "Block api from reaching db").incidents == []  # outage mode was not in the postmortem
    assert by_title(after, "Add latency between web and api").incidents == []  # different component


def test_resource_exhaustion_is_history_driven():
    pm = Postmortem("b.md", "Disk full on api", services=["api", "pay-provider"], modes=["resource-exhaustion"])
    _, exps = plan([pm])
    targets = [e.target for e in exps if e.kind == "resource-exhaustion"]
    assert targets == ["api"]  # not the external provider
    assert by_title(exps, "Exhaust a resource on one instance of api").incidents == ["Disk full on api"]


def test_coverage_notes():
    inv, _ = plan()
    pms = [Postmortem("x.md", "Office wifi"), Postmortem("y.md", "Odd one", services=["api"]),
           Postmortem("z.md", "Fine", services=["api"], modes=["latency"])]
    notes = coverage_notes(inv, pms)
    assert any("pay-provider" in n and "external" in n for n in notes)
    assert any("solo-db has a single instance" in n for n in notes)
    assert any("Office wifi" in n and "not used" in n for n in notes)
    assert any("Odd one" in n and "failure mode" in n for n in notes)
    assert not any("Fine" in n for n in notes)
    assert not any(n.startswith("recs is tier 1") for n in notes)
