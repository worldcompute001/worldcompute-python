"""One two-camera inference and, optionally, one bounded SO100 shoulder target."""
import argparse
import asyncio
from datetime import datetime, timezone
import importlib
import math
import time

from .client import WorldCompute


def recent(timestamp):
    return timestamp.tzinfo is not None and 0 <= (
        datetime.now(timezone.utc) - timestamp).total_seconds() < 2


def check_pair(snapshot):
    state = (snapshot['robot_state'] or {}).get('payload', {})
    if state.get('robot_id') != 'so100' or state.get('unit') != 'rad':
        return None, 'missing SO100 telemetry in radians'
    if not recent(datetime.fromisoformat(state['observed_at'])):
        return None, 'station telemetry outside freshness window'
    views = {}
    for camera in snapshot['cameras']:
        name = camera['track_name']
        if name not in ('overhead', 'arm'):
            continue
        if name in views:
            raise ValueError(f'Ambiguous camera name: {name}')
        views[name] = camera
    if len(views) != 2:
        return None, f'missing cameras: {sorted({"overhead", "arm"} - views.keys())}'
    times = [c['captured_at_us'] for c in views.values()]
    if not all(times):
        return None, 'missing camera source timestamp'
    skew = max(times) - min(times)
    if skew > 200_000:
        return None, f'camera skew {skew / 1000:.1f} ms exceeds 200 ms'
    if not all(-.15 <= time.time() - t / 1e6 < 1 for t in times):
        ages = {name: round(time.time() - c['captured_at_us']/1e6, 3) for name, c in views.items()}
        return None, f'camera ages outside freshness window (seconds): {ages}'
    return (views, state['joints']), None


def paired(snapshot):
    return check_pair(snapshot)[0]


def hold_policy(views, joints):
    """Reference policy returning the measured shoulder angle in radians."""
    return joints['shoulder_pan']


async def run(policy, execute, *, target_name='robot'):
    mode = 'simulation' if target_name == 'sim' else 'physical'
    async with WorldCompute.for_target(target_name) as wc:
        if target_name == 'robot' and not wc.access_token:
            await wc.login(physical=execute)
        async with wc.observation_stream() as latest:
            async with asyncio.timeout(20):
                while not (inputs := paired(latest())):
                    await asyncio.sleep(.05)
            views, joints = inputs
            start = joints['shoulder_pan']
            print('Camera inputs:', [(n, c['width'], c['height']) for n, c in views.items()])
            wanted = await asyncio.to_thread(policy, views, dict(joints))
            if type(wanted) not in (int, float) or not math.isfinite(wanted):
                raise ValueError('Policy must return one finite shoulder angle in radians')
            target = start + max(-.02, min(.02, wanted - start))
            print('Measured, predicted, bounded target (rad):', start, wanted, target)
            if not execute:
                return
            async with wc.robot('so100', mode=mode) as arm:
                state = await arm.state()
                oldest_input = min(c['captured_at_us'] for c in views.values()) / 1e6
                if (time.time() - oldest_input > 5 or not paired(latest()) or state.get('robot_id') != 'so100'
                        or state.get('mode') != mode or state.get('unit') != 'rad'
                        or not recent(datetime.fromisoformat(state['observed_at']))
                        or not all(abs(state['joints'][k] - v) < .01 for k, v in joints.items())):
                    raise RuntimeError('Camera or robot state changed or expired')
                before = state['joints']['shoulder_pan']
                target = before + max(-.02, min(.02, target - before))
                request = await arm.target({'shoulder_pan': target})
                try:
                    result = await arm.wait(request)
                    print('Controller result:', result)
                    print('Measured shoulder change (rad):',
                          (await arm.state())['joints']['shoulder_pan'] - before)
                finally:
                    await arm.hold()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--policy', default='worldcompute.harness:hold_policy',
                        help='Importable module:function returning absolute shoulder radians')
    parser.add_argument('--execute', action='store_true', help='Send one physical target')
    args = parser.parse_args()
    module, function = args.policy.split(':', 1)
    asyncio.run(run(getattr(importlib.import_module(module), function), args.execute))
