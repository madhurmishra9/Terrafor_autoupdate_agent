# request_processor agent

See `SKILL.md` in this folder for the full behavioural contract. This README
summarises the agent's role, invocation point, and code locations.

## Where it lives in code

| Component | Path |
|-----------|------|
| Agent definition | `src/aws_driftguard/agents/definitions.py` |
| Skill | `skills/request_processor/SKILL.md` |
| Tools | `src/aws_driftguard/agents/tools_*.py` |

## Inputs and outputs

See the Output contract section of `SKILL.md`. Each agent reads its upstream
state key and writes exactly one output key, per the pipeline state contract in
`src/aws_driftguard/common/state.py`.

## Cross-references

Full pipeline order and per-agent detail: `docs/ARCHITECTURE.md`.
