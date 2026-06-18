# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

# acli (Atlassian CLI) is the tier-2 Jira mechanism. Install it in the image so
# the fallback chain has a real binary. Pin a version in your environment.
ENV ACLI_VERSION=1.0.0

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates git \
    && rm -rf /var/lib/apt/lists/*

# Install acli (adjust URL to your internal mirror / official release as needed)
# Left as a clearly-marked step so corporate environments can swap the source.
RUN curl -fsSL -o /usr/local/bin/acli \
        "https://acli.atlassian.com/linux/latest/acli" \
    && chmod +x /usr/local/bin/acli || echo "acli install skipped (provide via mirror)"

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY skills/ ./skills/
COPY pyproject.toml ./

ENV PYTHONPATH=/app/src
ENV SKILLS_ROOT=/app/skills
ENV PYTHONUNBUFFERED=1

# ADK web/server entrypoint. Adjust to your runner (adk run / adk web / custom).
CMD ["python", "-m", "terraform_driftguard.run"]
