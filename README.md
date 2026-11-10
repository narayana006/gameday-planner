# gameday-planner

Propose failure-injection experiments for game days from your architecture and past incidents.

> **Project status: planning. There is no working code in this repository yet.**
> This README describes what the project will do. Nothing below can be installed or run today.
> Features are ticked off in the checklist as they are built.

## What it is

A command-line tool.

**The problem it solves:** Teams skip game days because designing useful, safe experiments takes time nobody has.

## Who it is for

Teams who want to run resilience game days without spending days preparing.

## How it will work

1. You provide a list of services and dependencies, plus past postmortems.
2. The tool proposes experiments, each with a hypothesis, blast radius and abort conditions.
3. It exports a plan for people to review and run; it does not inject failures itself.

## Planned features

Unticked items are not built yet.

- [ ] Reads a service inventory or dependency map and past postmortems
- [ ] Proposes experiments with hypothesis, blast radius and abort conditions
- [ ] Ranks experiments by risk covered and effort
- [ ] Exports a game day plan in Markdown
- [ ] Planning only: it does not inject failures

## Planned usage

This is the intended interface, shown so you can judge the design. **It does not work yet**, and names may change before the first release.

```bash
gameday-planner plan --services services.yaml --postmortems ./postmortems
```

## Contributing

Feedback on the design is the most useful contribution right now. Open an issue to suggest a feature, question an approach or describe your use case. Code contributions are welcome once the first version lands.

## License

[MIT](LICENSE)
