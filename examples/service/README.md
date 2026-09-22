# relayd

A long-running service that watches a directory and relays new files to a
downstream endpoint with bounded retries and backpressure.

## What it does

Files dropped into a configured directory are picked up by the watcher, placed
on a bounded queue, and delivered to an HTTP endpoint. If the endpoint is
temporarily unavailable, deliveries retry on a bounded exponential-backoff
schedule. When the queue is full, the watcher pauses instead of buffering
without bound.

## Why it exists

A watched folder is a common, simple hand-off boundary between systems. Without
a dedicated process, files just sit there. With a naive loop, a slow or down
endpoint leads to duplicate deliveries and unbounded memory growth. relayd
turns the folder into a bounded, retrying, idempotent pipeline that can run for
weeks unattended.

## Getting started

```bash
python -m pip install -e .
relayd --watch ./incoming --endpoint https://example.com/ingest
```

Point a client at the service's `beacon.yaml` and ask the agent to explain the
retry policy or describe a safe first change. See
[docs/architecture.md](docs/architecture.md) for the pipeline and
[docs/operations.md](docs/operations.md) for operating it.

## Running the tests

```bash
python -m pytest tests/
```

All tests run offline. They never open a real socket or call a downstream
endpoint.
