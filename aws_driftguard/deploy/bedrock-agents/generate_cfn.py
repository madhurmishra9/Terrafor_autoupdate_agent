#!/usr/bin/env python3
"""Generate a CloudFormation template provisioning the managed Bedrock Agents.

Emits one Bedrock collaborator agent per pipeline stage (instruction = the
stage's SKILL.md), an action group per agent backed by the shared Lambda, and a
supervisor agent (multi-agent collaboration) that sequences them.

Usage:
    python deploy/bedrock-agents/generate_cfn.py > bedrock-agents.yaml
    aws cloudformation deploy --template-file bedrock-agents.yaml \\
        --stack-name aws-driftguard-agents --capabilities CAPABILITY_IAM
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make the package importable when run from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from aws_driftguard.orchestration.stages import STAGES  # noqa: E402
from aws_driftguard.skills_loader import load_skill  # noqa: E402


def _sanitize(name: str) -> str:
    return name.replace("Agent", "")


def generate() -> str:
    lines: list[str] = []
    lines.append("AWSTemplateFormatVersion: '2010-09-09'")
    lines.append("Description: AWS DriftGuard managed Bedrock Agents (one per stage + supervisor)")
    lines.append("Parameters:")
    lines.append("  FoundationModel:")
    lines.append("    Type: String")
    lines.append("    Default: anthropic.claude-sonnet-4-6-20260514-v1:0")
    lines.append("  ActionLambdaArn:")
    lines.append("    Type: String")
    lines.append("    Description: ARN of the deployed lambda_action_group handler")
    lines.append("  AgentRoleArn:")
    lines.append("    Type: String")
    lines.append("    Description: IAM role ARN Bedrock assumes for the agents")
    lines.append("Resources:")

    collaborators: list[str] = []
    for spec in STAGES:
        res = _sanitize(spec.name) + "Agent"
        collaborators.append(res)
        # Instruction is the skill text (escaped for YAML block scalar).
        skill_text = load_skill(spec.skill).replace("\n", "\n        ")
        lines.append(f"  {res}:")
        lines.append("    Type: AWS::Bedrock::Agent")
        lines.append("    Properties:")
        lines.append(f"      AgentName: aws-driftguard-{_sanitize(spec.name).lower()}")
        lines.append("      AgentResourceRoleArn: !Ref AgentRoleArn")
        lines.append("      FoundationModel: !Ref FoundationModel")
        lines.append("      Instruction: |")
        lines.append(f"        {skill_text}")
        lines.append("      ActionGroups:")
        lines.append(f"        - ActionGroupName: {_sanitize(spec.name).lower()}-tools")
        lines.append("          ActionGroupExecutor:")
        lines.append("            Lambda: !Ref ActionLambdaArn")
        lines.append("          FunctionSchema:")
        lines.append("            Functions:")
        for tool in spec.tools:
            lines.append(f"              - Name: {tool}")
            lines.append(f"                Description: {tool.replace('_', ' ')}")

    # Supervisor with multi-agent collaboration.
    lines.append("  SupervisorAgent:")
    lines.append("    Type: AWS::Bedrock::Agent")
    lines.append("    Properties:")
    lines.append("      AgentName: aws-driftguard-supervisor")
    lines.append("      AgentResourceRoleArn: !Ref AgentRoleArn")
    lines.append("      FoundationModel: !Ref FoundationModel")
    lines.append("      AgentCollaboration: SUPERVISOR")
    lines.append("      Instruction: |")
    lines.append("        Coordinate the DriftGuard pipeline by invoking each collaborator")
    lines.append("        agent in strict order: RequestProcessor, Classification,")
    lines.append("        ChangeAnalyser, DecisionMaker, Terraform, Jira, PR. Pass each")
    lines.append("        agent's JSON output as context to the next. If any agent reports a")
    lines.append("        halt, stop the pipeline and return the reason.")
    lines.append("      AgentCollaborators:")
    for res in collaborators:
        lines.append(f"        - CollaboratorName: {res}")
        lines.append(f"          AgentDescriptor:")
        lines.append(f"            AliasArn: !GetAtt {res}.AgentArn")
    lines.append("Outputs:")
    lines.append("  SupervisorAgentId:")
    lines.append("    Value: !GetAtt SupervisorAgent.AgentId")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.stdout.write(generate())
