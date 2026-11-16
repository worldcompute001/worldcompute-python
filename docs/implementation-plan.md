# Standalone Python SDK

Owner and primary author: worldcompute001. Package contact: team@worldcompute.org.
Commits use the GitHub account's numeric-ID noreply address, not the personal account.

## Delivery steps

1. Package foundation and asynchronous session client, with injectable HTTP/LiveKit
   transports and deterministic tests. Repository: worldcompute001/worldcompute-python.
2. External developer authentication and admission in the World Compute backend,
   plus Python login and LiveKit connection. Keep browser controls compatible.
3. Runnable local simulation quickstart, documented physical opt-in, CI and build
   artifacts. Open a separate PR for each step; do not publish to PyPI yet.

## Existing implementation to reuse

world-compute-v0/apps/cloud-mcp/controls-client.ts defines the unified command
contract. controls-api.ts signs robot, mode, participant, boot and lease-bound
admission tickets. controls_sessions.py owns execution and measured results.
Do not implement a second executor or expose the station's private HTTP port.

Current public HTTP admission requires same-origin cookies, CSRF and a signed
browser LiveKit binding. Existing OAuth is registered for the ChatGPT confidential
client, not a public Python application. A Python package alone cannot provide a
working external quickstart: backend authentication/admission must be extended.
Do not document invented API keys, copy browser cookies, distribute client secrets,
or bypass the existing per-person queue and ownership checks.

Evaluate a public OAuth authorization-code client with PKCE and loopback callback,
reusing the existing identity provider and scoped principal checks. Bind SDK-issued
LiveKit credentials to the authenticated principal, just as browser credentials
are bound to their session. Explicit scope checks for read, simulation and motion.

## SDK behavior

Async context managers connect and release sessions. Simulation is the default.
Expose target, sequence, follow, jog, reset, state, hold and stop. Renewal runs
only for an active session. Transport loss cancels input production; it never
replays movement. Stable request IDs identify uncertain outcomes. Arrival-waiting
methods inspect measured completion and report cancellation/timeout distinctly.
Cleanup attempts stop before disconnect; unconfirmed stop is reported honestly.

## Acceptance evidence

Build/install wheel into a clean environment; test denied authentication,
wrong-owner admission, expired leases, RPC failures, renewal failure, cleanup,
stream deadlines and measured completion. Run the documented command from outside
the website against simulation, confirming physical ownership remains untouched.
A physical reset requires fresh readiness and attended clearance. Mock tests and
simulation do not establish physical qualification.
