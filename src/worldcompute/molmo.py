"""Run one two-camera Molmo inference for the SO100."""
import argparse
import asyncio
import json
import os
import time
from pathlib import Path

from .harness import run
from .so101_mapping import arm_target, model_state, wc_targets
from .task_rollout import run_task


def usage_event(event, **values):
    fd = os.environ.get('WC_RUN_USAGE_FD')
    if fd:
        data = dict(event=event, at=time.monotonic(), **values)
        os.write(int(fd), (json.dumps(data) + '\n').encode())


def predict(session, prompt, mapping, views, joints, *, task=False, segment=False):
    import numpy as np
    from dreamscale import so101

    def rgb(name):
        camera = views[name]
        return np.frombuffer(camera['rgb'], dtype=np.uint8).reshape(
            camera['height'], camera['width'], 3)

    obs = so101.observation(side_frame=rgb('overhead'), wrist_frame=rgb('arm'),
                            joint_positions=model_state(joints, mapping))
    usage_event('request', frames=2)
    started = time.monotonic()
    chunk = session.predict(obs, instruction=prompt)
    rows = np.asarray(chunk.actions)
    timing = getattr(chunk, 'timing', None)
    usage_event('response', latency_ms=(time.monotonic() - started) * 1000,
                action_values=int(rows.size), upload_bytes=getattr(timing, 'upload_bytes', None),
                inference_ms=getattr(timing, 'server_inference_ms', None))
    if rows.shape != (30, 6):
        raise ValueError(f'Unexpected Molmo action shape {rows.shape}')
    if task:
        # Sample a short lookahead (sixth 30 Hz setpoint), then replan from measurements.
        print('Predicted gripper opening (%) at steps 1, 6, 12, 18, 24, 30:',
              rows[[0, 5, 11, 17, 23, 29], 5].tolist(), flush=True)
        selected = np.array(rows[:3] if segment else rows[5:6], dtype=float, copy=True)
        if not np.isfinite(selected).all():
            raise ValueError('Nonfinite Molmo waypoint')
        selected[:, 5] = np.clip(selected[:, 5], 0, 100)
        targets = wc_targets(selected, mapping)
        return targets if segment else targets[0]
    return arm_target('shoulder_pan', rows[0, 0], mapping)


def replay(path, policy):
    from PIL import Image

    data = json.loads(path.read_text())
    state = data['robot_state']['payload']
    if state.get('robot_id') != 'so100' or state.get('unit') != 'rad':
        raise ValueError('Expected measured SO100 joint positions in radians')
    views = {}
    for camera in data['cameras']:
        name = camera['track_name']
        if name in views:
            raise ValueError(f'Ambiguous camera name {name}')
        with Image.open(path.parent / camera['file']) as image:
            frame = image.convert('RGB')
            views[name] = dict(width=frame.width, height=frame.height, rgb=frame.tobytes())
    print('Recorded-input prediction (rad):', policy(views, state['joints']))


def add_arguments(parser):
    parser.add_argument('--target', choices=('sim', 'robot'), default='robot', help='Observation and control destination')
    parser.add_argument('--prompt', required=True)
    parser.add_argument('--mapping', type=Path,
                        default=Path.home() / '.config/worldcompute/so100-mapping.json',
                        help='SO100 calibration mapping (default: %(default)s)')
    parser.add_argument('--task', action='store_true', help='Use all joints and replan after each measured waypoint')
    parser.add_argument('--segment', action='store_true', help='Use the first three consecutive Molmo targets in task mode')
    parser.add_argument('--steps', type=int, default=12, help='Maximum waypoints for --task (1–30)')
    parser.add_argument('--seconds', type=float, metavar='N',
                        help='Maximum live task-loop duration in seconds (default: 90)')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--replay', type=Path, metavar='OBSERVATION_JSON')
    modes.add_argument('--execute', action='store_true', help='Send bounded targets to the selected SO100')


def run_args(parser, args):
    if args.seconds is not None:
        if not args.task or args.replay:
            parser.error('--seconds requires a live --task run')
        if not 0 < args.seconds <= 90:
            parser.error('--seconds must be greater than zero and at most 90')
    if args.segment and not args.task:
        parser.error('--segment requires --task')
    if not 1 <= args.steps <= 30:
        parser.error('--steps must be between 1 and 30')
    if not args.prompt.strip():
        parser.error('Provide a nonempty task prompt')
    if not args.mapping.is_file():
        parser.error(f'Missing SO100 mapping at {args.mapping}. Supply --mapping PATH.')
    mapping = json.loads(args.mapping.read_text())
    import dreamscale
    with dreamscale.connect(model='molmoact2-so101', keep_warm=0, startup_timeout=120,
                            idle_timeout=180) as session:
        usage_event('session_ready')
        contract = session.contract
        if (contract.action_dim, contract.chunk_size, contract.action_hz) != (6, 30, 30):
            raise ValueError('Unexpected Molmo action contract')

        def policy(views, joints):
            return predict(session, args.prompt, mapping, views, joints, task=args.task, segment=args.segment)

        if args.replay:
            replay(args.replay, policy)
        elif args.task:
            print('Run ended:', asyncio.run(run_task(policy, args.execute, args.steps, seconds=args.seconds or 90, target_name=args.target)))
        else:
            asyncio.run(run(policy, args.execute, target_name=args.target))
    usage_event('session_closed')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_arguments(parser)
    run_args(parser, parser.parse_args())
