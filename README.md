# gameday-planner

Propose failure-injection experiments for a game day from your service dependency map and past postmortems, ranked by the risk they cover against the effort they take.

**Status: first working version (0.1.0).** It reads a service inventory (YAML or JSON) and a directory of postmortems, generates experiments with a hypothesis, blast radius, abort conditions and rollback, ranks them, and exports a Markdown or JSON plan. Experiments come from a fixed set of seven templates and postmortems are matched by keywords, not understood; see [Limitations](#limitations).

**Planning only.** The tool writes a document. It never injects a failure, runs a command or opens a network connection, and a test enforces that the package imports nothing that could.

## Install

```bash
pip install git+https://github.com/narayana006/gameday-planner
```

Python 3.10 or newer. The only dependency is PyYAML.

## Quick start

The repository ships a fictional shop (`examples/services.yaml`) and four invented postmortems. `--top 3` keeps the output short; the default is 8.

````console
$ gameday-planner plan --services examples/services.yaml --postmortems examples/postmortems --top 3
# Game day plan

> This is a plan for people to review and run. gameday-planner does not inject failures and has not touched any system.

Inputs: 10 services, 11 dependencies, 4 postmortems. 32 candidate experiments were generated; the top 3 are below.

## Ranked experiments

Priority is risk covered divided by an effort factor (low 1, medium 1.5, high 2). Risk counts the most critical tier reached, downstream services, past incidents rehearsed and untested assumptions.

| # | Experiment | Priority | Risk | Effort | Blast radius | Past incidents |
| --- | --- | --- | --- | --- | --- | --- |
| E1 | Flush product-cache (cold cache) | 7.5 | 7.5 | low | large | 1 |
| E2 | Add latency between checkout-api and payments-provider | 5 | 7.5 | medium | medium | 1 |
| E3 | Add latency between storefront-web and checkout-api | 4.67 | 7 | medium | medium | 1 |

## E1. Flush product-cache (cold cache)

- **Type:** cache-loss
- **Target:** product-cache
- **Why now:** reaches a tier 1 service; 3 downstream services could be affected; rehearses 1 past incident.
- **Past incidents:** Catalog errors after product-cache was flushed (2026-01-20)
- **Hypothesis:** Callers fall through to the source of truth, which handles the extra load; latency rises but stays within SLO and the cache refills within 15 minutes.
- **Method:** Flush all keys in product-cache, or restart it with an empty dataset, during normal traffic.
- **Blast radius:** large. If the hypothesis is wrong, impact could reach: product-cache, catalog-api, recommendations, storefront-web.
- **Where to run:** Staging first. In production only in a low-traffic window, on a fraction of traffic, with every affected owner present.
- **Abort if:**
  - Error rate or latency on catalog-api, storefront-web breaches its SLO alert threshold for more than 2 minutes.
  - Load on the backing datastore goes above 80% of its capacity.
  - Impact appears on any service outside the expected set (product-cache, catalog-api, recommendations, storefront-web).
  - A real incident is declared, or anyone on the call asks to stop.
- **Rollback:** Nothing to undo; throttle callers or pre-warm the cache if the backing store is struggling.

## E2. Add latency between checkout-api and payments-provider

- **Type:** dependency-latency
- **Target:** checkout-api -> payments-provider
- **Why now:** reaches a tier 1 service; 1 downstream service could be affected; rehearses 1 past incident; hard dependency with no fallback.
- **Past incidents:** Checkout slowdown during payments-provider latency (2025-09-14)
- **Hypothesis:** With 2 seconds added to every call to payments-provider, timeouts in checkout-api cut the calls off, its thread and connection pools do not fill up, and its own latency stays within SLO or it sheds load cleanly.
- **Method:** Inject 2 seconds of delay on calls from checkout-api to payments-provider (proxy fault rule or traffic shaping on the caller side) for 10 minutes, starting with 10% of calls.
- **Blast radius:** medium. If the hypothesis is wrong, impact could reach: checkout-api, storefront-web.
- **Where to run:** Production during business hours with the owning team present, or staging if no one has run it before.
- **Abort if:**
  - Error rate or latency on checkout-api, storefront-web breaches its SLO alert threshold for more than 5 minutes.
  - Thread or connection pool usage in checkout-api goes above 90%.
  - Impact appears on any service outside the expected set (checkout-api, storefront-web).
  - A real incident is declared, or anyone on the call asks to stop.
- **Rollback:** Remove the delay rule and confirm pool usage returns to normal.

## E3. Add latency between storefront-web and checkout-api

- **Type:** dependency-latency
- **Target:** storefront-web -> checkout-api
- **Why now:** reaches a tier 1 service; rehearses 1 past incident; hard dependency with no fallback.
- **Past incidents:** Checkout slowdown during payments-provider latency (2025-09-14)
- **Hypothesis:** With 2 seconds added to every call to checkout-api, timeouts in storefront-web cut the calls off, its thread and connection pools do not fill up, and its own latency stays within SLO or it sheds load cleanly.
- **Method:** Inject 2 seconds of delay on calls from storefront-web to checkout-api (proxy fault rule or traffic shaping on the caller side) for 10 minutes, starting with 10% of calls.
- **Blast radius:** medium. If the hypothesis is wrong, impact could reach: storefront-web.
- **Where to run:** Production during business hours with the owning team present, or staging if no one has run it before.
- **Abort if:**
  - Error rate or latency on storefront-web breaches its SLO alert threshold for more than 5 minutes.
  - Thread or connection pool usage in storefront-web goes above 90%.
  - Impact appears on any service outside the expected set (storefront-web).
  - A real incident is declared, or anyone on the call asks to stop.
- **Rollback:** Remove the delay rule and confirm pool usage returns to normal.

## Gaps and notes

- payments-provider is used by checkout-api but not declared; treated as an external dependency
- catalog-db has a single instance: there is no failover to test. Consider a restore-from-backup drill instead.
- Postmortem 'Office wifi outage' (2026-02-08-office-wifi.md) mentions no service from the inventory and was not used.

## Before the game day

- [ ] Each experiment has a named owner and the owning team has reviewed its hypothesis and abort conditions.
- [ ] Dashboards and alerts for every service in the blast radius are open and known to work.
- [ ] The rollback for each experiment has been rehearsed or at least read aloud.
- [ ] On-call and support know the schedule; a single person has authority to stop everything.
- [ ] Results (hypothesis held or not, surprises, follow-up actions) will be written down per experiment.
````

Write the plan to a file with `-o plan.md`, or get the same data as JSON with `--format json`.

## The service inventory

```yaml
services:
  - name: checkout-api
    tier: 1                 # 1 = customer-facing critical, 2 = default, 3 = best effort
    replicas: 4             # default 1
    owner: payments         # optional
    type: service           # service (default), database, cache, queue or external
    depends_on:
      - orders-db           # a plain name is a hard dependency
      - name: session-cache
        fallback: true      # the caller claims it can cope without it
      - name: order-events
        critical: false     # optional for the caller
```

A dependency that is not declared as a service (such as a third-party API) is treated as `external`: experiments block or slow the caller's traffic to it, never the third party itself. A JSON file with the same structure works too.

## Postmortems

Every `.md`, `.markdown` or `.txt` file under the directory is read. For each one the tool extracts:

- the title (first `# heading`) and a date (`YYYY-MM-DD` in the file name or text);
- which inventory services it is about: those named in the title or a "Root cause" section, otherwise any named anywhere;
- failure modes, by phrase: dependency outage, latency, failover, resource exhaustion, overload, cache loss, instance loss.

An experiment "rehearses" a postmortem when the failing component and the failure mode both match. Postmortems that match nothing are listed under "Gaps and notes" so you can see what was ignored.

## What gets proposed

| Experiment | Proposed for |
| --- | --- |
| Terminate one instance | every `service` |
| Block caller from a dependency | every dependency edge |
| Add latency to a dependency | every dependency edge |
| Fail over the primary | every `database` with 2 or more replicas |
| Flush the cache | every `cache` |
| Pause consumers to build a backlog | every `queue` |
| Exhaust a resource on one instance | services with a past resource-exhaustion incident |

The hypothesis changes with what the inventory claims: a dependency with `fallback: true` must keep serving, a hard dependency must fail fast and recover, a `critical: false` one must not matter.

### Ranking

`priority = risk / effort factor`

- **Risk** starts from the most critical tier the experiment can reach (tier 1 = 3, tier 2 = 2, tier 3 = 1), plus 0.5 per downstream service (up to 4), plus 3 per past incident it rehearses, plus 1 for a hard dependency with no fallback or a single-instance service, plus 0.5 for a declared fallback that has to be proven.
- **Effort factor** is 1 for low effort (terminate an instance, flush a cache), 1.5 for medium (network faults, backlog, resource pressure) and 2 for high (database failover).

Every experiment lists the reasons behind its score under "Why now".

### Blast radius

The blast radius is the worst case: the target plus every service that depends on it, directly or transitively. It is `large` when that set has three or more services including a tier 1 service, `medium` when it has three or more services or any tier 1 service, otherwise `small`. The level sets the recommended environment and how quickly the SLO abort condition triggers (2 minutes for large, 5 otherwise).

## Options

```text
gameday-planner plan --services FILE [--postmortems DIR] [--top N]
                     [--format markdown|json] [--title TEXT] [-o FILE]
```

Exit codes: `0` plan written, `2` bad input.

## Features

- [x] Reads a service inventory or dependency map and past postmortems
- [x] Proposes experiments with hypothesis, blast radius and abort conditions
- [x] Ranks experiments by risk covered and effort
- [x] Exports a game day plan in Markdown (and JSON)
- [x] Planning only: it does not inject failures
- [ ] Import the dependency map from Kubernetes, a service catalog or tracing data
- [ ] Zone and region failure experiments
- [ ] Custom experiment templates and scoring weights
- [ ] Record results after the game day and feed them into the next plan

## Limitations

- The plan is only as good as the inventory. Tiers, replica counts and `fallback` flags are taken at face value; the tool cannot check them.
- Seven built-in experiment templates. There is nothing yet for zone or region loss, DNS, certificates, clock skew or bad deploys, and templates cannot be added without editing the code.
- Postmortems are matched by service name and a fixed list of English phrases. A postmortem that describes a failure in other words is reported as unmatched, and one that mentions a phrase in passing can be over-counted. Always read the "Past incidents" line before trusting a ranking.
- Abort conditions refer to "the SLO alert threshold" generically; the tool does not know your SLOs, dashboards or alert names. Fill those in during review.
- Durations and thresholds in the text (2 seconds of latency, 10 minutes, 90% pool usage) are starting points, not values derived from your system.
- The scoring weights are fixed and are a heuristic for ordering a discussion, not a measurement of risk.

## Development

```bash
git clone https://github.com/narayana006/gameday-planner
cd gameday-planner
pip install -e ".[test]"
pytest
```

## Contributing

Issues and pull requests are welcome. New experiment templates (with hypothesis, abort conditions and rollback wording) and failure-mode phrases that postmortems really use are the most valuable additions.

## Author

Built and maintained by [Narayana Vemburaj](https://github.com/narayana006).

## License

[MIT](LICENSE)
