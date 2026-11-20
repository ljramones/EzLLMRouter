# Runtime resource ownership

## Limits

| Resource | Limit and behavior |
| --- | --- |
| Controlled execution | Four worker threads and at most 64 running or queued actions per Coordinator. |
| Successor execution | Two worker threads and at most 64 running or queued actions per service. |
| HTTP, sender IPC, worker IPC and console ingress | At most 32 active connections per listener. Excess connections close without creating another handler thread. |
| HTTP input | A 15-second absolute header/body deadline, checked at each underlying socket read. No per-request timer thread. The completed input restores the ordinary socket timeout before model processing. |
| IPC records | At most 262,144 bytes. Accepted sender/worker connections allow five seconds for the entire incoming frame and five seconds for writing the reply. |
| Worker exchange | Connect, request and response share the caller's total attempt budget plus the existing bounded protocol allowance. Cancelling the worker's async exchange closes its socket immediately. |
| Console ingress | Three seconds to connect upstream, five seconds per write, a 30-second idle wait and a six-minute connection lifetime. |
| Operator wire tokens | A 30-minute lifetime and at most 4,096 live tokens per registry. Issue/authentication prune expired entries; capacity exhaustion preserves existing live credentials. |
| Browser sessions | At most four per principal and 64 per application; ordinary sessions occupy at most 56 slots. New logins replace that principal's oldest session. Eviction and shutdown revoke attached wire credentials. |

Execution queue exhaustion records a definite failure before transmission, with a
recoverable work handle and HTTP 503. It does not invoke the provider or leave a
successor reservation inflight. A failed executor submission is also gated against
Python's enqueue-before-thread-creation behavior: the rejected action cannot run
later if another thread drains that queue.

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

Listeners shut down their active sockets and join their handler threads before
returning from `server_close()`. Shutdown waits for accepted work and its existing
I/O deadlines; it does not cancel a paid attempt merely because its caller stopped
waiting. New requests cannot publish a session after operator shutdown starts.

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

The same resource helper is copied explicitly into the isolated worker and the
credential-free ingress. It contains no service, database or provider dependencies.
The worker's import-only package checks verify that the trusted server package
remains unavailable there. Frozen dependency versions, hashes and wheel inputs
are unchanged.

## Validation

The offline resource regressions use actual socket pairs, real event-loop threads,
barriers, injected startup failures and disposable SQLite stores. They cover queue
limits, failed submission after enqueue, shutdown waits, completed-future retention,
reservation release, expired/revoked tokens, session shutdown, partial frames,
blocked replies, async socket cancellation, HTTP deadlines without timer threads,
startup cleanup and local-service dependency order. They invoke no model providers
and do not bind a listener.

Run the full offline checks with `uv run --locked python -m tools.check`.
Socket-listener and frozen-worker target qualification remain separate checks;
run `uv run --locked python -m tools.check --http-only` in the owner Terminal and
validate the explicitly staged worker with the already reviewed frozen inputs
before accepting a rebuilt deployment. No existing profile is restarted by these
source checks.
