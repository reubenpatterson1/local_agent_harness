FROM python:3.13-slim

# bash should already be present in this base image; curl is installed
# explicitly so exfiltration-style injected payloads that expect curl to be
# available can actually be attempted and observed.
RUN apt-get update && apt-get install -y --no-install-recommends curl bash \
    && rm -rf /var/lib/apt/lists/*

COPY qwen-agent-unsafe /usr/local/bin/qwen-agent-unsafe
RUN chmod +x /usr/local/bin/qwen-agent-unsafe

WORKDIR /workspace
RUN mkdir -p /workspace

# Stay up and idle by default. qwen-agent-unsafe is run interactively per
# test via `docker compose exec agent qwen-agent-unsafe ...`, not started
# automatically as a workload.
CMD ["sleep", "infinity"]
