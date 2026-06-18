# Orchestration — AWS DriftGuard (native Bedrock)

AWS DriftGuard runs natively on Amazon Bedrock. There are two orchestration
modes, selected by `ORCHESTRATION_MODE`.

## Mode 1: `converse` (default, runnable)

A code-driven orchestrator (`orchestration/bedrock_orchestrator.py`) runs the 7
stages sequentially. Each stage is a **Bedrock Converse tool-use loop**:

1. The stage's `SKILL.md` is the system prompt.
2. The stage's tools are registered as Bedrock `toolSpec`s
   (`orchestration/tool_registry.py`, built by signature introspection).
3. The model calls tools; `tool_registry.dispatch` executes the shared Python
   tool functions; results are fed back until the model emits final JSON.
4. The result is written to the shared state under the stage's `output_key`.

A centralised `pipeline_halted` flag short-circuits downstream stages (same
stop-guard contract as the GCP edition). Connectivity guards probe Jira / GitHub
before the stages that need them. This mode runs with only AWS credentials —
no pre-provisioned agents.

## Mode 2: `agents` (managed Bedrock Agents)

For teams that want managed multi-agent collaboration:

- `deploy/bedrock-agents/generate_cfn.py` emits a CloudFormation template with
  one Bedrock Agent per stage (instruction = that stage's `SKILL.md`), an action
  group per agent backed by a shared Lambda, and a **supervisor** agent
  (`AgentCollaboration: SUPERVISOR`) that sequences the collaborators.
- `deploy/bedrock-agents/lambda_action_group.py` is the action-group executor —
  it dispatches to the **same** `tool_registry`, so behaviour matches mode 1.
- At runtime, `orchestration/bedrock_agents_runtime.py` invokes the provisioned
  supervisor via `bedrock-agent-runtime`.

Provision once:
```bash
python deploy/bedrock-agents/generate_cfn.py > bedrock-agents.yaml
aws cloudformation deploy --template-file bedrock-agents.yaml \
  --stack-name aws-driftguard-agents --capabilities CAPABILITY_IAM
export BEDROCK_SUPERVISOR_AGENT_ID=<output> ORCHESTRATION_MODE=agents
```

## Shared across both modes

The pipeline shape, tools, skills, state contract, ADF/Jira/GitHub clients, and
all accuracy/optimisation features are identical to the other editions. Only the
LLM (Bedrock), datastore (RDS), secrets (Secrets Manager), compute (ECS/EKS),
and orchestration framework differ.
