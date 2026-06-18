# Orchestration — Azure DriftGuard (native Azure)

Azure DriftGuard runs natively on Azure OpenAI. Two orchestration modes,
selected by `ORCHESTRATION_MODE`.

## Mode 1: `sdk` (default, runnable)

A code-driven orchestrator (`orchestration/azure_orchestrator.py`) runs the 7
stages sequentially. Each stage is an **Azure OpenAI tool-use loop**:

1. The stage's `SKILL.md` is the system prompt.
2. The stage's tools are registered as OpenAI function tools
   (`orchestration/tool_registry.py:openai_specs_for`).
3. The model calls tools; `tool_registry.dispatch` executes the shared Python
   tool functions; results are fed back until the model emits final JSON.
4. The result is written to shared state under the stage's `output_key`.

A centralised `pipeline_halted` flag short-circuits downstream stages.
Connectivity guards probe Jira / GitHub before the stages that need them. Runs
with an Azure OpenAI endpoint + credentials only.

## Mode 2: `connected` (managed Azure AI Agent Service)

For teams that want managed agents in an Azure AI project
(`orchestration/agent_service_runtime.py`):

- One Azure AI **agent per stage** (instruction = that stage's `SKILL.md`,
  function tools = the stage's tools), created via the `azure-ai-agents` SDK.
- The agents run sequentially over a shared **thread**, each agent's JSON output
  passed as context to the next.
- Function tools wrap the **same** `tool_registry`, so behaviour matches mode 1.

Requires `AZURE_AI_PROJECT_ENDPOINT` (an Azure AI Foundry project). Auth via
`DefaultAzureCredential` (managed identity on AKS).

## Shared across both modes

The pipeline shape, tools, skills, state contract, ADF/Jira/GitHub clients, and
all accuracy/optimisation features are identical to the other editions. Only the
LLM (Azure OpenAI), datastore (Azure SQL), secrets (Key Vault), compute (AKS),
and orchestration framework differ.
