"""Load and validate the service inventory (YAML or JSON)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml

KINDS = ("service", "database", "cache", "queue", "external")


class InventoryError(ValueError):
    pass


@dataclass
class Dependency:
    name: str
    critical: bool = True  # the caller cannot do its job without it
    fallback: bool = False  # the caller claims a fallback (cache, default, queue-and-retry)


@dataclass
class Service:
    name: str
    kind: str = "service"
    tier: int = 2  # 1 = customer-facing critical, 3 = internal / best effort
    replicas: int = 1
    owner: str = ""
    depends_on: list[Dependency] = field(default_factory=list)
    declared: bool = True  # False for dependencies that appear only as a target


@dataclass
class Inventory:
    services: dict[str, Service]
    warnings: list[str] = field(default_factory=list)

    def dependents(self, name: str) -> list[str]:
        """Every service that depends on ``name``, directly or transitively, nearest first."""
        seen: list[str] = []
        frontier = [name]
        while frontier:
            current = frontier.pop(0)
            for svc in self.services.values():
                if svc.name not in seen and svc.name != name and any(d.name == current for d in svc.depends_on):
                    seen.append(svc.name)
                    frontier.append(svc.name)
        return seen


def _dependency(raw, owner: str) -> Dependency:
    if isinstance(raw, str):
        return Dependency(raw)
    if isinstance(raw, dict) and isinstance(raw.get("name"), str):
        return Dependency(raw["name"], bool(raw.get("critical", True)), bool(raw.get("fallback", False)))
    raise InventoryError(f"service {owner!r}: each depends_on entry must be a name or a mapping with 'name'")


def parse_inventory(data) -> Inventory:
    entries = data.get("services") if isinstance(data, dict) else data
    if not isinstance(entries, list) or not entries:
        raise InventoryError("inventory must contain a non-empty 'services' list")
    services: dict[str, Service] = {}
    for raw in entries:
        if not isinstance(raw, dict) or not isinstance(raw.get("name"), str) or not raw["name"].strip():
            raise InventoryError("every service needs a 'name'")
        name = raw["name"].strip()
        if name in services:
            raise InventoryError(f"duplicate service name: {name}")
        kind = str(raw.get("type", raw.get("kind", "service"))).lower()
        if kind not in KINDS:
            raise InventoryError(f"service {name!r}: type must be one of {', '.join(KINDS)}")
        try:
            tier, replicas = int(raw.get("tier", 2)), int(raw.get("replicas", 1))
        except (TypeError, ValueError):
            raise InventoryError(f"service {name!r}: tier and replicas must be integers") from None
        if tier not in (1, 2, 3):
            raise InventoryError(f"service {name!r}: tier must be 1, 2 or 3")
        if replicas < 1:
            raise InventoryError(f"service {name!r}: replicas must be at least 1")
        deps = raw.get("depends_on") or []
        if not isinstance(deps, list):
            raise InventoryError(f"service {name!r}: depends_on must be a list")
        services[name] = Service(name, kind, tier, replicas, str(raw.get("owner", "")),
                                 [_dependency(d, name) for d in deps])
    inventory = Inventory(services)
    for svc in list(services.values()):
        for dep in svc.depends_on:
            if dep.name == svc.name:
                raise InventoryError(f"service {svc.name!r} depends on itself")
            if dep.name not in services:
                # Undeclared targets are treated as third-party systems we cannot inject into directly.
                services[dep.name] = Service(dep.name, kind="external", tier=svc.tier, declared=False)
                inventory.warnings.append(
                    f"{dep.name} is used by {svc.name} but not declared; treated as an external dependency")
    return inventory


def load_inventory(path: str | Path) -> Inventory:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InventoryError(f"cannot read {path}: {exc.strerror}") from None
    try:
        data = json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)
    except (yaml.YAMLError, json.JSONDecodeError) as exc:
        raise InventoryError(f"{path} is not valid {'JSON' if path.suffix == '.json' else 'YAML'}: {exc}") from None
    return parse_inventory(data)
