"""Attended, measured waypoint rollout over one World Compute session."""
import asyncio
from datetime import datetime
import math
import time

from . import trace
from .client import WorldCompute
from .harness import check_pair


async def observe_after(latest, after):
    deadline = time.monotonic() + 20
    while True:
        snapshot = latest()
        inputs, reason = check_pair(snapshot)
        if inputs:
            views, joints = inputs
            stamp = datetime.fromisoformat(snapshot['robot_state']['payload']['observed_at'])
            if stamp.timestamp() > after and all(c['captured_at_us'] / 1e6 > after
                                                 for c in views.values()):
                return views, joints
            reason = 'waiting for observations captured after the last waypoint'
        if time.monotonic() >= deadline:
            raise TimeoutError(f'Observation unavailable: {reason}')
        await asyncio.sleep(.05)


def checked_positions(state, measured, clock_bounds, mode='physical'):
    failures = []
    for key, expected in (('robot_id', 'so100'), ('unit', 'rad'), ('mode', mode)):
        if state.get(key) != expected:
            failures.append(f'{key}={state.get(key)!r} (expected {expected!r})')
    try:
        stamp = datetime.fromisoformat(state['observed_at'])
        if stamp.tzinfo is None:
            raise ValueError('Missing timestamp timezone')
        earliest, latest = clock_bounds
        minimum, maximum = earliest - stamp.timestamp(), latest - stamp.timestamp()
        age_text = f'[{minimum:.4f}, {maximum:.4f}]s'
        if not 0 <= minimum <= maximum < 2:
            failures.append('controller timestamp outside [0, 2) seconds')
    except (KeyError, TypeError, ValueError):
        age_text = 'unavailable'
        failures.append('missing or invalid controller timestamp')
    positions = state.get('joints')
    deltas = []
    for name, original in measured.items():
        value = positions.get(name) if isinstance(positions, dict) else None
        if type(value) not in (int, float) or not math.isfinite(value - original):
            failures.append(f'invalid controller reading for {name}')
            deltas.append(f'{name}=unavailable')
            continue
        delta = value - original
        deltas.append(f'{name}={delta:+.6f}')
        if abs(delta) > .01:
            failures.append(f'{name} drift exceeds 0.01 rad')
    if failures:
        raise RuntimeError('Pre-move check failed: ' + '; '.join(failures)
                           + f'; controller age={age_text}; controller minus observation (rad): '
                           + ', '.join(deltas))
    return positions


async def controller_positions(arm, measured):
    state = await arm.state()
    bounds = arm.station_time_bounds()
    try:
        stamp = datetime.fromisoformat(state['observed_at'])
        observed = stamp.timestamp() if stamp.tzinfo is not None else None
    except (KeyError, TypeError, ValueError):
        observed = None
    # A newly sampled pose can fall inside the RPC clock uncertainty interval.
    # Wait until the whole interval can verify its age, then apply both limits.
    if observed is not None and bounds[0] < observed <= bounds[1] and bounds[1] - bounds[0] < 2:
        await asyncio.sleep(observed - bounds[0])
        bounds = arm.station_time_bounds()
    from .playground_sim import PlaygroundSim
    return checked_positions(state, measured, bounds, 'simulation' if isinstance(arm, PlaygroundSim) else 'physical')


class TrackingIncomplete(RuntimeError):
    pass


async def wait_for_tracking(arm, target):
    """Check the encoder residual after controller completion without resending."""
    deadline = time.monotonic() + 1.0
    while True:
        measured = (await arm.state())['joints']
        residual = {k: target[k] - measured[k] for k in target}
        if all(math.isfinite(v) and abs(v) <= .01 for v in residual.values()):
            return measured
        if time.monotonic() >= deadline:
            raise TrackingIncomplete(f'Waypoint tracking incomplete; target minus measured (rad): {residual}')
        await asyncio.sleep(.1)


async def rollout(policy, latest, arm, steps):
    after = 0
    step = 0
    stalled = False
    while step < steps:
        for attempt in range(3):
            views, measured = await observe_after(latest, after)
            wanted = await asyncio.to_thread(policy, views, dict(measured))
            segment = wanted if isinstance(wanted, list) else [wanted]
            if not segment or any(set(row) != set(measured) or not all(math.isfinite(v) for v in row.values()) for row in segment):
                raise ValueError('Expected one finite target per measured joint')
            oldest = min(c['captured_at_us'] for c in views.values()) / 1e6
            reason = 'prediction input expired'
            while time.time() - oldest <= 5:
                inputs, reason = check_pair(latest())
                if inputs:
                    before = await controller_positions(arm, measured) if arm is not None else measured
                    inputs, reason = check_pair(latest())
                    if inputs and time.time() - oldest <= 5:
                        break
                await asyncio.sleep(.05)
            else:
                message = f'Step {step}: prediction input age {time.time()-oldest:.2f}s; {reason or "expired during validation"}'
                if attempt == 2:
                    raise RuntimeError(message + '; inference retry limit reached')
                print(message + '; replanning', flush=True)
                continue
            break
        for index, wanted in enumerate(segment[:steps-step]):
            if index:
                before = await controller_positions(arm, settled)
                if not check_pair(latest())[0] or time.time() - oldest > 5:
                    print('Segment observation expired; replanning', flush=True)
                    break
            step += 1
            delta = {k: wanted[k] - v for k, v in before.items()}
            # Scale the entire waypoint together to preserve the model's joint-space direction.
            scale = .02 / max(.02, *(abs(v) for v in delta.values()))
            target = {k: v + scale * delta[k] for k, v in before.items()}
            trace.event('waypoint', step=step, measured_rad=before, wanted_rad=wanted,
                        scale=scale, submitted_rad=target)
            print(f'Step {step}:', target, flush=True)
            if arm is None:
                return 'preview'
            started = time.monotonic()
            try:
                request = await arm.target(target)
                result = await arm.wait(request, timeout=10)
                trace.event('controller_completed', step=step, request=request, result=result)
            except Exception as error:
                trace.event('controller_failed', step=step, error_type=type(error).__name__)
                raise
            try:
                settled = await wait_for_tracking(arm, target)
            except TrackingIncomplete as error:
                if len(segment) == 1 or stalled:
                    raise
                await arm.hold()
                print(f'{error}; discarding remaining targets and replanning', flush=True)
                stalled = True
                after = time.time()
                break
            stalled = False
            trace.event('measured', step=step, joints_rad=settled)
            print(f'Measured after {time.monotonic()-started:.3f}s:', settled, flush=True)
            after = time.time()
    return 'step limit reached'


async def timed_rollout(policy, latest, arm, steps, seconds):
    deadline = asyncio.timeout(seconds)
    try:
        async with deadline:
            return await rollout(policy, latest, arm, steps)
    except TimeoutError:
        if deadline.expired():
            return 'time limit reached'
        raise


async def run_task(policy, execute, steps, *, seconds=90, target_name='robot'):
    mode = 'simulation' if target_name == 'sim' else 'physical'
    async with WorldCompute.for_target(target_name) as wc:
        if target_name == 'robot' and not wc.access_token:
            await wc.login(physical=execute)
        async with wc.observation_stream() as read:
            def latest():
                return read(synchronized_pair=True)

            if not execute:
                return await timed_rollout(policy, latest, None, 1, seconds)
            async with wc.robot('so100', mode=mode) as arm:
                try:
                    return await timed_rollout(policy, latest, arm, steps, seconds)
                finally:
                    await arm.hold()
