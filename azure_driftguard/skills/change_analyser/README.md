# change_analyser agent

See `SKILL.md` in this folder for the full behavioural contract. This README
summarises the agent's role, invocation point, and code locations.

## Where it lives in code

| Component | Path |
|-----------|------|
| Agent definition | `src/azure_driftguard/agents/definitions.py` |
| Skill | `skills/change_analyser/SKILL.md` |
| Tools | `src/azure_driftguard/agents/tools_*.py` |

## Inputs and outputs

See the Output contract section of `SKILL.md`. Each agent reads its upstream
state key and writes exactly one output key, per the pipeline state contract in
`src/azure_driftguard/common/state.py`.

## Cross-references

Full pipeline order and per-agent detail: `docs/ARCHITECTURE.md`.
