# Pipeline architecture

relayd is a small pipeline with four moving parts. This document is the
reference an agent should read before changing the data flow.

## Data flow

1. The **watcher** scans the input directory on a fixed cadence and enqueues new
   files onto a bounded queue.
2. The **queue** holds files awaiting delivery. When full, it signals the
   watcher to pause intake (backpressure).
3. A set of **delivery workers** drain the queue and POST each file to the
   downstream endpoint.
4. On failure, the **retry policy** decides whether to retry and after how long.

The stages are independent and testable in isolation. Each stage reads only the
queue and writes only to the next stage, so a fault in one does not tear down
the others.

## Bounded queue

The queue has a fixed capacity. Producers wait when it is full rather than
growing it, so a downstream outage cannot expand memory without limit. The
queue is persisted to disk so a restart does not lose files that were accepted
but not yet delivered.

## Retry and deduplication

Every delivery carries a stable key derived from the file path and content
digest. A retry re-sends the same key, so a downstream consumer can detect and
skip a duplicate. The backoff is capped: after the maximum attempt count, the
file is moved to a dead-letter directory and the failure is logged.

## Shutdown

Shutdown is cooperative. The watcher stops scanning, the queue stops accepting
new work, and the delivery workers drain in-flight work before the process
exits. Signals trigger this path so a restart never abandons a half-written
delivery.
