# Local SearXNG for qwen-agent `search`

Self-contained search backend for the `search` tool in `../bin/qwen-agent`.
Nothing in this directory depends on an external drive.

| Item | Value |
| --- | --- |
| Endpoint | `http://127.0.0.1:8888` (loopback only, no auth) |
| Container | `qwen-agent-searxng` |
| Image | `searxng/searxng@sha256:11a9b34c...` (pinned by digest) |
| Vendored image | `image/searxng-11a9b34c.tar` (89 MB) |

## Bring up

```bash
cd ~/qwen-agent-workspace/searxng
docker compose up -d
```

Docker Desktop must be running first (`open -a Docker`), or compose fails with
`failed to connect to the docker API`.

## Offline bring-up

The image is vendored, so no network or registry access is needed:

```bash
docker load -i image/searxng-11a9b34c.tar
docker compose up -d
```

## Verify

`docker ps` only proves the container started, not that search works. JSON
output is disabled in stock SearXNG and returns HTTP 403, so test the format
the agent actually uses:

```bash
curl -s 'http://127.0.0.1:8888/search?q=test&format=json' | head -c 200
```

Expect HTTP 200 and a `results` array. An empty array or a 403 means
`settings.yml` was not mounted.

## Two load-bearing settings

Both live in `settings.yml` and are the difference between working and
silently returning nothing:

- `server.limiter: false` — the default botdetection limiter rejects the
  instance's own loopback callers.
- `search.formats` must include `json` — JSON output is off by default and
  `/search?format=json` returns HTTP 403 without it.

This is why the image is pinned by digest rather than `:latest`: an upstream
change to either default would break the agent's search tool at the next
bring-up, with no local diff to explain it.

## Tear down

```bash
docker compose down          # keep the named volumes
docker compose down -v       # also drop searxng-config / searxng-cache
```
