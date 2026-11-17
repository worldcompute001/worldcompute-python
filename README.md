# World Compute Python SDK

Control a registered World Compute robot from a Python program on your computer.
Use the same API for its simulated twin and physical arm. Source and primary
maintainer: [World Compute](https://github.com/worldcompute001), team@worldcompute.org.

**Prerelease:** not published to PyPI. Production SDK authentication is deployed.
The standalone quickstart has passed against the remote simulated twin: OAuth
login, LiveKit admission, measured reset completion, and stop/release. Physical
SDK motion has not been tested. Sign in using OAuth PKCE; no API key is required.

## Install and run

Requires Python 3.11+, an authorized World Compute account, an online station,
and outbound HTTPS/WebRTC connectivity. Use a local desktop; login listens only
on 127.0.0.1:8765. That port must be free. Complete login within ten minutes; use the newly opened
page rather than an older sign-in tab. Login starts on the canonical OAuth issuer
to preserve its cookies across account sign-in. It does not work through an arbitrary
remote notebook without forwarding its loopback callback.

```bash
git clone https://github.com/worldcompute001/worldcompute-python.git
cd worldcompute-python
# Until the PRs merge, use the complete review branch:
git switch sdk/quickstart
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python examples/quickstart.py
```

The example opens account login, discovers registered arms, connects through
LiveKit, resets the **simulation**, polls measured completion, and stops/releases
the session. Simulation does not claim or move the physical arm. The station must
still be connected. The roster is configuration, not proof of motor readiness.

To command hardware, first check the arm and clear its path, then run:

```bash
python examples/quickstart.py --robot so100 --physical
```

Physical mode requires an explicit confirmation and grants robot:control during
login. It uses the existing exclusive queue and calibrated limits. Reset is not
an out-of-range recovery routine; missing motor limits must be resolved by the
operator. Stop holds position; it does not remove motor power.

## Your own program

```python
import asyncio
from worldcompute import WorldCompute

async def main():
    async with WorldCompute() as wc:
        await wc.login()  # use physical=True only when you need real motion
        robots = await wc.robots()
        async with wc.robot(robots[0]['id'], mode="simulation") as robot:
            request = await robot.reset()
            result = await robot.wait(request)
            print(result)

asyncio.run(main())
```

OAuth credentials remain in memory. Access tokens refresh while making HTTP
requests. For automation an already authorized access token may be supplied via
`WC_ACCESS_TOKEN`; it expires and has no automatic refresh without a login grant.
Never share tokens, use browser cookies or embed the confidential ChatGPT secret.

## Commands

| Method | Input / behavior |
|---|---|
| `target(positions)` | Named joint targets, radians |
| `sequence_targets(waypoints)` | List of `{positions, pause_ms?, timeout_ms?}` |
| `follow(positions)` | Reliable updates of named target positions |
| `jog(velocities)` | Initialize a velocity stream, radians/second |
| `publish_jog(velocities)` | Latest-input data packets after jog initialization |
| `reset()` | This registered arm's saved reset pose |
| `wait(request_id)` | Require measured completion, not just acceptance |
| `state()` | Read state and execution history |
| `hold()` | End the current action, retain the session |
| `stop()` | Close and release the session |

Target/sequence/reset accept `request_id=` for stable correlation. Command methods
return that ID after acceptance. Context managers renew sessions every two seconds
and attempt stop before disconnect. Hold before changing action types. If renewal
or transport fails, new inputs are blocked; there is no automatic replay.

`OutcomeUnknown.request_id` identifies an uncertain command. Inspect the original
execution rather than resending under a new ID. A transport failure may also leave
Stop unconfirmed; the SDK raises instead of claiming the arm stopped. A powered
robot requires an attended hardware stop procedure if communications are lost.

## Development and release

```bash
python -m pip install -e '.[test]'
pytest -q
python -m build
```

Tests use isolated HTTP/LiveKit doubles and do not qualify physical movement.
Backend tests separately exercise OAuth and admission. Live end-to-end simulation
and attended physical testing must be reported separately. PyPI publishing is not
configured; release ownership and credentials must be confirmed before publishing.
