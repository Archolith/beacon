# Operations notes

How to run, monitor, and safely restart relayd in production.

## Running

The service is configured with three things: the directory to watch, the
downstream endpoint, and the maximum queue capacity. Start it with:

```bash
relayd --watch ./incoming --endpoint https://example.com/ingest
```

Logs go to stderr and are line-oriented JSON, so they are easy to forward or
tail. Nothing is written to the watched directory by the service itself.

## Monitoring

The health endpoint reports three numbers: queue depth, in-flight deliveries,
and the count of dead-lettered files. A persistent non-zero dead-letter count is
the signal to investigate, not the queue depth, which is expected to fluctuate
during an outage.

## Restarting

Shutdown is graceful: send a termination signal, wait for the drain to finish,
then restart. Because the queue is persisted and deliveries are idempotent, a
restart is safe even mid-outage. Do not delete the queue directory unless you
accept losing accepted-but-undelivered files.

## Failure model

A downstream outage is not a service failure. The service retries and applies
backpressure. A file that exhausts its retries moves to dead-letter and is never
silently dropped. The two genuine incidents are disk-full on the queue directory
and a misconfigured endpoint, both of which fail loudly in logs.
