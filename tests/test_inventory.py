import json

import pytest

from gameday_planner.inventory import InventoryError, load_inventory, parse_inventory


def inv(*services):
    return parse_inventory({"services": list(services)})


def test_defaults_and_dependency_forms():
    i = inv({"name": "api", "depends_on": ["db", {"name": "cache", "critical": False, "fallback": True}]},
            {"name": "db", "type": "database", "tier": 1, "replicas": 3, "owner": "data"},
            {"name": "cache", "kind": "cache"})
    api = i.services["api"]
    assert (api.kind, api.tier, api.replicas) == ("service", 2, 1)
    assert [(d.name, d.critical, d.fallback) for d in api.depends_on] == [("db", True, False), ("cache", False, True)]
    assert (i.services["db"].kind, i.services["db"].owner, i.services["cache"].kind) == ("database", "data", "cache")
    assert i.warnings == []


def test_undeclared_dependency_becomes_external_with_warning():
    i = inv({"name": "api", "tier": 1, "depends_on": ["payments-provider"]})
    ext = i.services["payments-provider"]
    assert ext.kind == "external" and not ext.declared and ext.tier == 1
    assert "not declared" in i.warnings[0]


def test_dependents_are_transitive_and_survive_cycles():
    i = inv({"name": "web", "depends_on": ["api"]}, {"name": "api", "depends_on": ["db"]},
            {"name": "worker", "depends_on": ["db"]}, {"name": "db", "type": "database"},
            {"name": "a", "depends_on": ["b"]}, {"name": "b", "depends_on": ["a"]})
    assert i.dependents("db") == ["api", "worker", "web"]  # nearest first
    assert i.dependents("web") == []
    assert i.dependents("a") == ["b"]


@pytest.mark.parametrize("data,match", [
    ({}, "non-empty 'services' list"),
    ({"services": []}, "non-empty"),
    ({"services": [{"tier": 1}]}, "needs a 'name'"),
    ({"services": [{"name": "a"}, {"name": "a"}]}, "duplicate"),
    ({"services": [{"name": "a", "type": "lambda"}]}, "type must be one of"),
    ({"services": [{"name": "a", "tier": 5}]}, "tier must be 1, 2 or 3"),
    ({"services": [{"name": "a", "tier": "top"}]}, "must be integers"),
    ({"services": [{"name": "a", "replicas": 0}]}, "at least 1"),
    ({"services": [{"name": "a", "depends_on": "b"}]}, "must be a list"),
    ({"services": [{"name": "a", "depends_on": [{"critical": True}]}]}, "mapping with 'name'"),
    ({"services": [{"name": "a", "depends_on": ["a"]}]}, "depends on itself"),
])
def test_invalid_inventories(data, match):
    with pytest.raises(InventoryError, match=match):
        parse_inventory(data)


def test_load_yaml_json_and_errors(tmp_path):
    y = tmp_path / "s.yaml"
    y.write_text("services:\n  - name: api\n    replicas: 2\n")
    assert load_inventory(y).services["api"].replicas == 2
    j = tmp_path / "s.json"
    j.write_text(json.dumps([{"name": "api"}]))  # a bare list is accepted too
    assert list(load_inventory(j).services) == ["api"]
    bad = tmp_path / "bad.yaml"
    bad.write_text("services: [unclosed")
    with pytest.raises(InventoryError, match="not valid YAML"):
        load_inventory(bad)
    with pytest.raises(InventoryError, match="cannot read"):
        load_inventory(tmp_path / "missing.yaml")
