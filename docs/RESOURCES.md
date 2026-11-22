# Runtime resource ownership

## Limits

| Resource | Limit and behavior |
| --- | --- |
| Controlled execution | Four worker threads and at most 64 running or queued actions per Coordinator. |
| Successor execution | Two worker threads and at most 64 running or queued actions per service. |
| HTTP, sender IPC, worker IPC and console ingress | At most 32 active connections per listener. Excess connections close without creating another handler thread. |
| HTTP input | A 15-second absolute header/body deadline, checked at each underlying socket read. No per-request timer thread. The completed input restores the ordinary socket timeout before model processing. |
| IPC records | At most 262,144 bytes and 64 nested levels below the record object. Deep JSON and decoder recursion failures are input errors on synchronous and asynchronous paths. Accepted sender/worker connections allow five seconds for the entire incoming frame and five seconds for writing the reply. |
| Worker exchange | Connect, request and response share the caller's total attempt budget plus the existing bounded protocol allowance. Cancelling the worker's async exchange closes its socket immediately. |
| Console ingress | Three seconds to connect upstream, five seconds per write, a 30-second idle wait and a six-minute connection lifetime. |
| Operator wire tokens | A 30-minute lifetime and at most 4,096 live tokens per registry. Issue/authentication prune expired entries; capacity exhaustion preserves existing live credentials. |
| Report readers | Four independent read-only WAL snapshots; ten-second SQL budget. Decoding/aggregation runs outside the writer lock. |
| Trusted sender checks | Two threads, at most 32 running/queued checks. Fresh checks and the first nonblocking write share the authority gate on a check thread, leaving the response loop free. |
| Gateway diagnostics | Queue of 1,024 rows, four-MiB files with two backups, at most 64 KiB per row. Overview exposes written/dropped/write-error counters. Cached bounded tails are diagnostic only. |
| Browser sessions | At most four per principal and 64 per application; ordinary sessions occupy at most 56 slots. New logins replace that principal's oldest session. Eviction and shutdown revoke attached wire credentials. |

The maintained [limit inventory](../tests/fixtures/contracts/transport-security/limits.json)
links every row to registered boundary or lifecycle regressions. Additional rows
cover login/password limits, HTTP body ceilings, client/provider response sizes
and attempt timeouts. Capacity tests accept the documented limit, refuse or
evict the next entry as specified, and check recovery. Deadline tests use injected
clocks or bounded socket fixtures; these checks do not qualify production load
or container signal timing.

Ingress preserves the response direction after the client half-closes its write
side. If an upstream parser rejects a request before its body finishes arriving,
the relay drains the remaining client input while forwarding the rejection,
within the same connection deadline and fixed upstream target.

Execution queue exhaustion records a definite failure before transmission, with a
recoverable work handle and HTTP 503. It does not invoke the provider or leave a
successor reservation inflight. A failed executor submission is also gated against
Python's enqueue-before-thread-creation behavior: the rejected action cannot run
later if another thread drains that queue.
A submission failure moves the pool into `recovering`: accepted actions drain
once, then a fresh bounded pool accepts new work. The rejected action is never
replayed. If replacement allocation fails, status and later submissions retry
allocation while readiness remains unavailable. Shutdown prevents recovery.
The sender status exposes execution/check-pool state, inflight count, capacity,
submission failures and recoveries; service readiness requires both pools ready.

Completed execution futures are removed under a lock. Durable SQLite submissions,
results and usage remain available independently of the in-memory futures.

## Shutdown order

Call `Coordinator.close()` or `SuccessorService.close()` before closing the store
or injected transport. They stop new submissions, wait for existing admission
calls, then drain accepted execution. Coordinator also closes its explicitly
attached successor service. These methods leave injected stores and transports
to their owner and support repeated calls.

The local service registers cleanup immediately after acquiring each resource.
Normal shutdown and failed startup unwind dependencies in this order:

1. Stop the operator listener, stop maintenance/scheduling and drain operator jobs
   while the wire API remains available.
2. Stop the wire listener and drain its handler threads.
3. Close Coordinator and any attached successor, retaining final usage and results.
4. Close the sender's listener, transports and event loop.
5. Close SQLite.

Listeners shut down their active sockets and allow a combined five seconds for
handler joins. A remaining handler raises a shutdown error; the rest of the owned
cleanup still runs. Shutdown drains accepted Coordinator work and its existing
I/O deadlines; it does not cancel a paid attempt merely because its caller stopped
waiting. New requests cannot publish a session after operator shutdown starts.

The isolated worker handles SIGTERM by unwinding its listener and loop ownership.
It closes the worker loop before joining IPC handlers. Compose enables an init
process for service/worker, gives the service 330 seconds to drain its maximum
300-second attempt, and stops the worker afterward with a 15-second grace period.
These container signal/timing behaviors require target Docker qualification.

## Gateway startup and cleanup

The trusted sender, in-process ASGI adapter and isolated worker share a small
standard-library-only loop owner. Startup failures and timeouts cancel scheduled
startup, close any partially created clients/transports, stop the loop thread and
close the loop. Cleanup still stops the loop when client shutdown raises. Pending
async tasks are cancelled during loop teardown; this relies on cooperative Python
cancellation, rather than forcibly terminating arbitrary threads.

Socket collisions are checked before starting loop resources. A failed socket
bind/activation or permission change closes the partial listener. Cleanup removes
only the socket-path identity recorded after its own bind; it preserves a path
that another owner has replaced.

`runtime_resources.py` composes the typed admission/executor implementation in
`execution_resources.py`, loop ownership, and the dependency-free connection
limits in `connection_resources.py`. The explicit isolated-worker package receives
those helpers; the credential-free ingress receives only the connection helper.
The shared helpers import package peers and the standard library on the worker
path. Import qualification verifies that the trusted server package is unavailable.
Frozen dependency versions, hashes and wheel inputs are unchanged.

## Validation

The offline resource regressions use actual socket pairs, real event-loop threads,
barriers, injected startup failures and disposable SQLite stores. They cover queue
limits, failed submission after enqueue, shutdown waits, completed-future retention,
reservation release, expired/revoked tokens, session shutdown, partial frames,
blocked replies, async socket cancellation, HTTP deadlines without timer threads,
startup cleanup and local-service dependency order. They invoke no model providers
and do not bind a listener.

Pending-task cancellation and already-closed connection cleanup have explicit
regressions that force those states. Their coverage must not depend on a cancelled
future or a handler finishing before listener/loop shutdown begins. A failed loop
submission also verifies that its unscheduled coroutine closes and later work
still runs. The HTTP tier also runs the forced connection-cap, already-closed
stream and bounded-handler-join cases. Their reviewed coverage sets must match
across local and CI runs, independent of incidental handler completion.
Socket-budget fixtures live in a separate test module so loading the loopback
inventory preserves `sys.path` and does not load the isolated-worker fixture.

Run the full offline checks with `uv run --locked python -m tools.check`.
Socket-listener and frozen-worker target qualification remain separate checks;
run `uv run --locked python -m tools.check --http-only` in the owner Terminal and
validate the explicitly staged worker with the already reviewed frozen inputs
before accepting a rebuilt deployment. No existing profile is restarted by these
source checks.
