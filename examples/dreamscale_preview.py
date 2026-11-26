"""Preview one DreamScale prediction from a recorded WC observation.

The mapping file must contain physically verified joint signs/zeros and gripper
endpoints. Default execution only validates inputs. --predict bills one request.
"""
import argparse
from dataclasses import asdict
from importlib.metadata import version
import json
from pathlib import Path

from worldcompute.so101_mapping import JOINTS, model_state, wc_targets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('observation', type=Path)
    parser.add_argument('--mapping', type=Path, required=True)
    parser.add_argument('--scene', type=int, required=True)
    parser.add_argument('--wrist', type=int, required=True)
    parser.add_argument('--prompt', required=True)
    parser.add_argument('--predict', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f'Output already exists: {args.output}')
    data = json.loads(args.observation.read_text())
    mapping = json.loads(args.mapping.read_text())
    if args.scene == args.wrist or min(args.scene, args.wrist) < 0:
        raise ValueError('Select two distinct recorded camera views')
    cameras = [data['cameras'][args.scene], data['cameras'][args.wrist]]
    state = data['robot_state']['payload']
    if state.get('unit') != 'rad':
        raise ValueError('WC measured joint units must explicitly be rad')
    if (state.get('configuration_revision') and mapping.get('configuration_revision')
            and state['configuration_revision'] != mapping['configuration_revision']):
        raise ValueError('Recorded state and mapping configuration revisions differ')
    if not args.prompt.strip():
        raise ValueError('A task prompt is required')
    values = model_state(state['joints'], mapping)
    result = {'mode': 'recorded-input-preview', 'model': 'molmoact2-so101',
              'source': str(args.observation.resolve()), 'mapping': mapping,
              'prompt': args.prompt, 'cameras': cameras, 'model_state': values,
              'model_state_units': 'five arm degrees, then gripper percent'}
    if args.predict:
        import numpy as np
        from PIL import Image
        import dreamscale
        from dreamscale import so101
        frames = [np.array(Image.open(args.observation.parent / c['file']).convert('RGB')) for c in cameras]
        # Replay deliberately presents the saved scene as a new observation. Original
        # timestamps remain in the source artifact. This script has no motor path.
        observation = so101.observation(side_frame=frames[0], wrist_frame=frames[1], joint_positions=values)
        with dreamscale.connect(model='molmoact2-so101', keep_warm=0, startup_timeout=120, idle_timeout=60) as policy:
            contract = policy.contract
            if contract.action_dim != 6 or contract.action_hz != 30 or contract.chunk_size != 30:
                raise ValueError('Unexpected model contract; preview stopped')
            chunk = policy.predict(observation, instruction=args.prompt)
            rows = np.asarray(chunk.actions).tolist()
            result.update(raw_actions=rows, contract=asdict(contract),
                          timing=asdict(chunk.timing), sdk_version=version('dreamscale'),
                          observation_id=chunk.observation_id, chunk_id=chunk.chunk_id,
                          capture_time_ns=chunk.capture_time_ns, action_hz=contract.action_hz)
            try:
                result['wc_target_preview'] = wc_targets(rows, mapping)
            except ValueError as error:
                result['conversion_error'] = str(error)
    with args.output.open('x') as output:
        json.dump(result, output, indent=2)
    print(f'Saved preview to {args.output.resolve()}')


if __name__ == '__main__':
    main()
