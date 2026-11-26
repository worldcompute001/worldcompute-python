# World Compute Python SDK

Control a registered World Compute robot from a Python program on your computer.
Use the same API for its simulated twin and physical arm. Source and primary
maintainer: [World Compute](https://github.com/worldcompute001), team@worldcompute.org.

**Alpha release:** [worldcompute 0.1.0a1](https://pypi.org/project/worldcompute/0.1.0a1/) is available on PyPI. Production SDK authentication is deployed.
The standalone quickstart has passed against the remote simulated twin: OAuth
login, LiveKit admission, measured reset completion, and stop/release. Physical
SDK reset also passed on SO100 with all six measured joints within 0.5° of the saved pose, followed by stop/release. Other physical command modes are not qualified by that reset test. Sign in using OAuth PKCE; no API key is required.

## Install and run

Install and run without cloning:

```bash
python -m pip install worldcompute==0.1.0a1
worldcompute-quickstart
```

This is an alpha release; pin the version when evaluating the SDK.

Requires Python 3.11+, an authorized World Compute account, an online station,
and outbound HTTPS/WebRTC connectivity. Use a local desktop; login listens only
on 127.0.0.1:8765. That port must be free. Complete login within ten minutes; use the newly opened
page rather than an older sign-in tab. Login uses the authorization endpoint advertised by World Compute, currently
`https://worldcompute.org/oauth/auth`, so it shares the regular account sign-in.
The callback still verifies the separately advertised OAuth issuer. It does not work through an arbitrary
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

To command hardware, first check the arm and clear its path, then run:

```bash
python examples/quickstart.py --robot so100 --physical
```

Physical mode requires an explicit confirmation and grants robot:control during
login. It uses the existing exclusive queue and calibrated limits. Reset is not
an out-of-range recovery routine; missing motor limits must be resolved by the
operator. Stop holds position; it does not remove motor power.

## Build a two-camera harness (0.1.0a2 release candidate)

Install this checkout with `python -m pip install .` or install the built
0.1.0a2 wheel into a Python 3.11+ environment. Run `worldcompute-harness`
on the machine where you can complete browser sign-in. The default reads
the SO100 overhead and wrist cameras and joint encoders, and previews a target
equal to the current shoulder position.

Supply your own synchronous Python function with the signature
`predict(views, joints) -> float`. Each view in `views["overhead"]` and
`views["arm"]` provides RGB24 bytes in `rgb`, pixel `width` and `height`,
and a source timestamp in microseconds. Joint values and the returned absolute
shoulder-pan target are in World Compute radians. Translate model units and
joint ordering inside your policy. For example, with an importable module
named `my_policy`, run:

```bash
worldcompute-harness --policy my_policy:predict
```

After reviewing the workspace and the preview, adding `--execute` runs a fresh
prediction and requests physical access to send one shoulder-pan target capped
at 0.02 rad from the measured position. The harness checks camera freshness,
input age and joint drift, then prints the controller result and measured delta.
A prediction older than five seconds is discarded at dispatch. Warm slow-starting
models before capture. For multi-step harnesses, use
`async with wc.observation_stream() as latest` and call `latest()` for snapshots
on the same connection. Check timestamps before each action.

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
and attended physical testing must be reported separately. See [release instructions](docs/releasing.md) for GitHub-to-PyPI trusted publishing.
Publishing requires the World Compute PyPI owner to register the publisher first.

## Camera observations and DreamScale preview (local development)

`await wc.observe(timeout=15)` opens the existing viewing connection and returns
RGB camera bytes with publisher identity, track SID/name, source capture time
when available, arrival time and the station's `wc.canary.state.v1` telemetry.
It requests only `/api/sdk/v1/live-token`. It gathers an observation over the
requested window and disconnects. Check each source's freshness and clock
before using it in a live policy. Missing telemetry is returned as `None`.

Capture both camera views and measured telemetry using account authorization:

```bash
python examples/capture_observation.py --output /tmp/wc-observation
```

The output contains PPM images and `observation.json`. Review the actual views
before selecting the scene and wrist indexes. Capture timestamps and camera
identities stay in the manifest. Availability of two physical cameras does not
establish that both publish into the viewing room.

`examples/dreamscale_preview.py` converts a saved observation for
`molmoact2-so101`. Supply an explicit mapping JSON with `joints` keyed by the
five WC arm joint names, each containing `sign` (1 or -1) and
`offset_degrees`, plus `gripper_closed_rad` and `gripper_open_rad`. Establish
these values against the provider's calibration convention and this unit's
saved calibration. The existing WC controller continues to own motor offsets.
An optional `configuration_revision` is compared when the recorded state also
provides one. Scene-camera placement must match the model profile.

```bash
python examples/dreamscale_preview.py /tmp/wc-observation/observation.json \
  --mapping /path/to/qualified-mapping.json --scene 0 --wrist 1 \
  --prompt 'Pick up the block' --output /tmp/input-preview.json
```

The default validates and saves the converted input locally. Adding `--predict`
opens one billable provider session, requests one prediction, saves raw actions
and the inverse conversion to WC named radians, then closes with `keep_warm=0`.
Run in an environment containing the reviewed `dreamscale==0.1.0a299`, Pillow
and NumPy, with the existing DreamScale login. The script presents the recorded
scene as a new replay observation and retains original timing in the manifest.
This example has no action dispatch. Physical compatibility and the station's
chunk timing still require qualification before adding execution.

A recorded-input experiment on 2026-11-19 captured two 1280×720 tracks (`overhead`
and `arm`) with 30 ms capture skew plus measured SO100 state. MolmoAct2 returned
30 six-value absolute actions at 30 Hz, with 168 ms observation-to-action latency
excluding startup. The station's saved Phosphobot calibration exactly matched
its reset snapshot. Its inverse transform reproduced the saved encoder positions.
The experimental projection used LeRobot 0.6.1's range-centered degrees, full-turn
wrist-roll convention and the unit's gripper endpoints. Overhead placement,
wrist lighting, calibration-range transfer and physical compatibility remain to
be qualified. The run dispatched no robot actions, and provider session listing
was empty after cleanup. An initial client contract-field error was corrected
before the successful prediction; the earlier session was also released.

## Run the Molmo harness

Install the wheel with its `molmo` extra or run `python -m pip install '.[molmo]'`
from this checkout. Sign in to DreamScale and supply the station's calibrated
SO100-to-SO101 mapping described above. Each invocation opens one hosted
MolmoAct2 session and requests one prediction.

```bash
mkdir -p ~/.config/worldcompute
cp /path/to/model-mapping.json ~/.config/worldcompute/so100-mapping.json
worldcompute run molmo --prompt "Turn slightly toward the blue toy"
```

The default uses the live overhead and wrist views and prints the predicted and
bounded shoulder angles. Add `--execute` for one physical shoulder target using
the existing SDK session checks and cleanup. For a hardware-free run, pass
`--replay /path/to/observation.json` from the camera capture example. The command
exits after one inference. A playground worker can launch it with an argument
list, passing the prompt as a single argument.

### Attended multi-joint tasks

`worldcompute run molmo --task --prompt "Pick up the blue toy"` previews a coordinated
waypoint from the five arm joints and gripper. Add `--execute` to run an attended
task. The runner samples the sixth setpoint of each prediction, constrains the
gripper to its calibrated opening range, and scales the joint displacement so
each waypoint is at most 0.02 rad per joint. After each measured completion it
requires newer camera frames and telemetry before predicting again. Use Ctrl+C
to end an attempt when the task is done or to interrupt it. Cleanup requests
hold and releases the session. A step limit (default 12, override with
`--steps 1..30`) or the execution deadline (default 90 seconds, shorten with e.g. `--seconds 15`) ends the attempt. The timer starts after model and station setup; hold and release run on exit. These
limits do not establish whether a grasp succeeded.

### Run Molmo in the local playground

Install the checkout with `pip install -e '.[molmo,sim]'`, with Google Chrome
installed and the local World Compute playground running on port 18835.
The same DreamScale credentials and SO100 mapping are used for both targets.

```sh
worldcompute run molmo --target sim --task --execute --seconds 15 --prompt "Can you pick up the toy?"
```

The SDK renders overhead and wrist RGB images from the playground scene, applies
the bounded joint target to its kinematic arm, then renders the updated pose
for the next inference. The toy is fixed in this scene. For a station run,
change `--target sim` to `--target robot`. Robot runs use the station login,
live cameras and controller. Omit `--execute` for a single prediction preview.
