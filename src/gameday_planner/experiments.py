"""Generate candidate experiments from the dependency graph and rank them.

Every experiment is a written proposal: hypothesis, method, blast radius,
abort conditions and rollback. Nothing in this module touches a real system.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .inventory import Dependency, Inventory, Service
from .postmortems import Postmortem

# kind -> (effort 1-3, postmortem failure mode that it rehearses)
KINDS: dict[str, tuple[int, str]] = {
    "instance-loss": (1, "instance-loss"),
    "cache-loss": (1, "cache-loss"),
    "dependency-outage": (2, "dependency-outage"),
    "dependency-latency": (2, "latency"),
    "queue-backlog": (2, "overload"),
    "resource-exhaustion": (2, "resource-exhaustion"),
    "failover": (3, "failover"),
}
EFFORT_LABEL = {1: "low", 2: "medium", 3: "high"}
EFFORT_FACTOR = {1: 1.0, 2: 1.5, 3: 2.0}  # priority = risk / factor
INCIDENT_WEIGHT = 3.0  # risk added per past incident an experiment rehearses
TIER_WEIGHT = {1: 3.0, 2: 2.0, 3: 1.0}


@dataclass
class Experiment:
    id: str
    kind: str
    title: str
    target: str
    hypothesis: str
    method: str
    affected: list[str]  # worst case: services that could see impact if the hypothesis is wrong
    blast_radius: str  # small | medium | large
    environment: str
    abort_conditions: list[str]
    rollback: str
    reasons: list[str] = field(default_factory=list)
    incidents: list[str] = field(default_factory=list)
    risk: float = 0.0
    effort: int = 1
    priority: float = 0.0

    @property
    def effort_label(self) -> str:
        return EFFORT_LABEL[self.effort]


def _blast(inv: Inventory, affected: list[str]) -> tuple[str, str]:
    tier1 = [n for n in affected if inv.services[n].tier == 1]
    if tier1 and len(affected) >= 3:
        return "large", "Staging first. In production only in a low-traffic window, on a fraction of traffic, with every affected owner present."
    if tier1 or len(affected) >= 3:
        return "medium", "Production during business hours with the owning team present, or staging if no one has run it before."
    return "small", "Production during business hours."


def _aborts(inv: Inventory, affected: list[str], level: str, extra: str) -> list[str]:
    watched = [n for n in affected if inv.services[n].tier == 1] or affected[:1]
    minutes = 2 if level == "large" else 5
    return [
        f"Error rate or latency on {', '.join(watched)} breaches its SLO alert threshold for more than {minutes} minutes.",
        extra,
        f"Impact appears on any service outside the expected set ({', '.join(affected)}).",
        "A real incident is declared, or anyone on the call asks to stop.",
    ]


def _build(inv: Inventory, postmortems: list[Postmortem], *, kind: str, target: str, failing: str,
           scope: str, title: str, hypothesis: str, method: str, abort: str, rollback: str,
           extra_reasons: list[tuple[float, str]] = ()) -> Experiment:
    """Assemble one experiment and compute its score.

    ``scope`` is the service whose dependents bound the blast radius;
    ``failing`` is the component that misbehaves, used to match past incidents.
    """
    affected = [scope] + inv.dependents(scope)
    level, environment = _blast(inv, affected)
    effort, mode = KINDS[kind]
    top_tier = min(inv.services[n].tier for n in affected)
    reasons = [f"reaches a tier {top_tier} service"]
    risk = TIER_WEIGHT[top_tier]
    downstream = len(affected) - 1
    if downstream:
        risk += min(downstream, 4) * 0.5
        reasons.append(f"{downstream} downstream service{'s' if downstream != 1 else ''} could be affected")
    matches = [p for p in postmortems if mode in p.modes and failing in p.services]
    if matches:
        risk += INCIDENT_WEIGHT * len(matches)
        reasons.append(f"rehearses {len(matches)} past incident{'s' if len(matches) != 1 else ''}")
    for bonus, reason in extra_reasons:
        risk += bonus
        reasons.append(reason)
    return Experiment(
        id="", kind=kind, title=title, target=target, hypothesis=hypothesis, method=method,
        affected=affected, blast_radius=level, environment=environment,
        abort_conditions=_aborts(inv, affected, level, abort), rollback=rollback, reasons=reasons,
        incidents=[f"{p.title} ({p.date})" if p.date else p.title for p in matches],
        risk=round(risk, 2), effort=effort, priority=round(risk / EFFORT_FACTOR[effort], 2),
    )


def _instance_loss(inv, pms, svc: Service) -> Experiment:
    if svc.replicas >= 2:
        hypothesis = (f"With one of {svc.replicas} instances gone, the remaining instances absorb the load; "
                      "users see no errors and the instance is replaced automatically.")
        extra = []
    else:
        hypothesis = (f"{svc.name} runs a single instance, so it will be unavailable until it restarts. "
                      "It restarts on its own within its recovery target and callers degrade as designed.")
        extra = [(1.0, "single instance, no redundancy")]
    return _build(
        inv, pms, kind="instance-loss", target=svc.name, failing=svc.name, scope=svc.name,
        title=f"Terminate one instance of {svc.name}",
        hypothesis=hypothesis,
        method=f"Terminate one running instance (pod, VM or task) of {svc.name} without draining it first.",
        abort=f"The terminated instance of {svc.name} is not replaced and healthy within 10 minutes.",
        rollback="Start a replacement instance manually, or scale the service back to its normal count.",
        extra_reasons=extra,
    )


def _dependency_pair(inv, pms, svc: Service, dep: Dependency) -> list[Experiment]:
    if dep.fallback:
        outage = (f"{svc.name} keeps serving from its fallback while {dep.name} is unreachable; "
                  "the degradation is visible on dashboards and no caller of it fails.")
        extra = [(0.5, "declared fallback has to be proven")]
    elif dep.critical:
        outage = (f"{svc.name} fails fast with clear errors instead of hanging, the right alert fires "
                  f"within 5 minutes, and it recovers without a restart once {dep.name} is back.")
        extra = [(1.0, "hard dependency with no fallback")]
    else:
        outage = (f"{dep.name} is optional for {svc.name}: requests still succeed without it, "
                  "with the optional feature missing.")
        extra = []
    link = f"{svc.name} -> {dep.name}"
    common = dict(target=link, failing=dep.name, scope=svc.name, extra_reasons=extra)
    return [
        _build(
            inv, pms, kind="dependency-outage", title=f"Block {svc.name} from reaching {dep.name}",
            hypothesis=outage,
            method=(f"Drop traffic from {svc.name} to {dep.name} only (network policy, proxy fault rule or "
                    f"firewall rule on the {svc.name} side) for 10 minutes. Do not touch {dep.name} itself."),
            abort=f"{svc.name} has not recovered 10 minutes after traffic to {dep.name} is restored.",
            rollback="Remove the blocking rule. Restart the caller's instances only if connections stay stuck.",
            **common),
        _build(
            inv, pms, kind="dependency-latency", title=f"Add latency between {svc.name} and {dep.name}",
            hypothesis=(f"With 2 seconds added to every call to {dep.name}, timeouts in {svc.name} cut the calls "
                        "off, its thread and connection pools do not fill up, and its own latency stays within SLO"
                        + (" by using the fallback." if dep.fallback else " or it sheds load cleanly.")),
            method=(f"Inject 2 seconds of delay on calls from {svc.name} to {dep.name} (proxy fault rule or "
                    "traffic shaping on the caller side) for 10 minutes, starting with 10% of calls."),
            abort=f"Thread or connection pool usage in {svc.name} goes above 90%.",
            rollback="Remove the delay rule and confirm pool usage returns to normal.",
            **common),
    ]


def _by_kind(inv, pms, svc: Service) -> list[Experiment]:
    if svc.kind == "database" and svc.replicas >= 2:
        return [_build(
            inv, pms, kind="failover", target=svc.name, failing=svc.name, scope=svc.name,
            title=f"Fail over the primary of {svc.name}",
            hypothesis=("A replica is promoted within 60 seconds, clients reconnect on their own, "
                        "no acknowledged writes are lost and write errors stay within the error budget."),
            method=(f"Trigger a controlled failover of the {svc.name} primary using the database's own "
                    "switchover procedure. Confirm replication lag is near zero before starting."),
            abort="No replica has been promoted after 2 minutes, or replication lag was not near zero at the start.",
            rollback="Promote the original primary again, or follow the database's failback runbook.")]
    if svc.kind == "cache":
        return [_build(
            inv, pms, kind="cache-loss", target=svc.name, failing=svc.name, scope=svc.name,
            title=f"Flush {svc.name} (cold cache)",
            hypothesis=("Callers fall through to the source of truth, which handles the extra load; "
                        "latency rises but stays within SLO and the cache refills within 15 minutes."),
            method=f"Flush all keys in {svc.name}, or restart it with an empty dataset, during normal traffic.",
            abort="Load on the backing datastore goes above 80% of its capacity.",
            rollback="Nothing to undo; throttle callers or pre-warm the cache if the backing store is struggling.")]
    if svc.kind == "queue":
        return [_build(
            inv, pms, kind="queue-backlog", target=svc.name, failing=svc.name, scope=svc.name,
            title=f"Pause consumers of {svc.name} to build a backlog",
            hypothesis=("Producers keep accepting work while consumers are paused for 15 minutes, the backlog "
                        "alert fires, and the backlog drains within 30 minutes of resuming with no lost messages."),
            method=f"Stop or scale to zero the consumers of {svc.name} for 15 minutes, then resume them.",
            abort="The backlog grows past what can be drained inside the queue's retention period.",
            rollback="Resume consumers and temporarily scale them up to drain the backlog.")]
    return []


def _resource_exhaustion(inv, pms, svc: Service) -> Experiment:
    return _build(
        inv, pms, kind="resource-exhaustion", target=svc.name, failing=svc.name, scope=svc.name,
        title=f"Exhaust a resource on one instance of {svc.name}",
        hypothesis=("The resource alert fires before users are affected, the unhealthy instance is taken "
                    "out of rotation automatically, and the other instances are not affected."),
        method=(f"On a single instance of {svc.name}, reproduce the resource pressure from the past incident "
                "(fill the data volume to 95%, or hold memory or connections) for 10 minutes."),
        abort="More than one instance becomes unhealthy, or co-located workloads are affected.",
        rollback="Release the resource (delete the filler file, stop the stress process) or replace the instance.")


def generate(inv: Inventory, postmortems: list[Postmortem] = ()) -> list[Experiment]:
    """Return every applicable experiment, best first, with ids E1..En in rank order."""
    pms = list(postmortems)
    out: list[Experiment] = []
    for svc in inv.services.values():
        if svc.kind == "external":
            continue  # third-party systems are only exercised from the caller's side
        if svc.kind == "service":
            out.append(_instance_loss(inv, pms, svc))
        out.extend(_by_kind(inv, pms, svc))
        for dep in svc.depends_on:
            out.extend(_dependency_pair(inv, pms, svc, dep))
        if any("resource-exhaustion" in p.modes and svc.name in p.services for p in pms):
            out.append(_resource_exhaustion(inv, pms, svc))
    out.sort(key=lambda e: (-e.priority, -e.risk, e.effort, e.title))
    for i, exp in enumerate(out, start=1):
        exp.id = f"E{i}"
    return out


def coverage_notes(inv: Inventory, postmortems: list[Postmortem]) -> list[str]:
    """Things the plan cannot cover or that deserve attention before the game day."""
    notes = list(inv.warnings)
    for svc in inv.services.values():
        if svc.kind == "database" and svc.replicas < 2:
            notes.append(f"{svc.name} has a single instance: there is no failover to test. "
                         "Consider a restore-from-backup drill instead.")
        elif svc.kind == "service" and svc.replicas < 2 and svc.tier == 1:
            notes.append(f"{svc.name} is tier 1 but runs a single instance.")
    for p in postmortems:
        if not p.services:
            notes.append(f"Postmortem '{p.title}' ({p.path}) mentions no service from the inventory and was not used.")
        elif not p.modes:
            notes.append(f"Postmortem '{p.title}' ({p.path}) did not match a known failure mode and did not affect ranking.")
    return notes
