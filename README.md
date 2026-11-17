# World Compute Python SDK

Control a registered World Compute robot from a Python program on your computer.
Use the same API for its simulated twin and physical arm. Source and primary
maintainer: [World Compute](https://github.com/worldcompute001), team@worldcompute.org.

**Alpha release:** [worldcompute 0.1.0a1](https://pypi.org/project/worldcompute/0.1.0a1/) is available on PyPI. Production SDK authentication is deployed.
The standalone quickstart has passed against the remote simulated twin: OAuth
login, LiveKit admission, measured reset completion, and stop/release. Physical
SDK reset also passed on SO100 with all six measured joints within 0.5° of the saved pose, followed by stop/release. Physical validation covered that reset. See the [World Compute Python guide](https://worldcompute.org/docs/controls) for setup and command examples.

## Install and run

Install and run without cloning:

```bash
python -m pip install worldcompute==0.1.0a1
worldcompute-quickstart
```

This is an alpha release; pin the version when evaluating the SDK.

Requires Python 3.11+, an online station, and outbound HTTPS/WebRTC connectivity.
Anyone can create a World Compute account and sign in. Browser sign-in and consent
give the SDK scoped, in-memory tokens through OAuth PKCE. There is no API key to create. Use a local desktop; login listens only
on 127.0.0.1:8765. That port must be free. Complete login within ten minutes; use the newly opened
page rather than an older sign-in tab. Login starts on the canonical OAuth issuer
to preserve its cookies across account sign-in. It does not work through an arbitrary
remote notebook without forwarding its loopback callback.

```bash
git clone https://github.com/worldcompute001/worldcompute-python.git
cd worldcompute-python
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python examples/quickstart.py
```

The example opens account login, discovers registered arms, connects through
LiveKit, resets the **simulation**, polls measured completion, and stops/releases
the session. Simulation does not claim or move the physical arm. The station must
still be connected. The roster is configuration, not proof of motor readiness.

After the simulation succeeds, have an operator watch the arm and clear its path.
Use the ID of the arm you intend to move. For the installed SDK, run the physical reset with:

```bash
worldcompute-quickstart --robot so100 --physical
```

Type `RESET` and approve physical control in the browser. Physical sessions share
the playground queue. If another session owns the arm, wait for your turn.
A physical reset requires fresh motor readings and valid calibrated limits. Reset is not
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
        if not robots:
            raise RuntimeError("No registered robot available")
        async with wc.robot(robots[0]['id'], mode="simulation") as robot:
            request_id = await robot.reset()
            print("Accepted request:", request_id)
            print("Measured completion:", await robot.wait(request_id))

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
| `sequence_targets(waypoints)` | List of waypoints with a `positions` dictionary and optional `pause_ms` and `timeout_ms` |
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
execution in `(await robot.state())["executions"]` when state is reachable. Avoid automatic retries. A transport failure may also leave
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
and attended physical testing must be reported separately. See [release instructions](docs/releasing.md) for GitHub-to-PyPI trusted publishing.
Publishing requires the World Compute PyPI owner to register the publisher first.
