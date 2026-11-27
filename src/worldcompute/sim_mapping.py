"""Geometric SO100 playground → SO101 mapping. Never a physical calibration."""
import math
from pathlib import Path
import json


def simulation_mapping():
    # Align SO101 base to playground with Rz(-pi/2). Lift/elbow then share zero.
    # Match approach (-Y in playground, +Z in SO101 tool) and jaw hinge axes.
    return dict(profile='playground-so100-geometric-v1', target='sim',
        provenance='Derived from phosphobot-radians-v1 and SO101 new-calibration joint frames; not physical calibration',
        joints={
            'shoulder_pan': dict(sign=-1, offset_degrees=0),
            'shoulder_lift': dict(sign=1, offset_degrees=0),
            'elbow_flex': dict(sign=1, offset_degrees=0),
            'wrist_flex': dict(sign=1, offset_degrees=90-math.degrees(1.6)),
            'wrist_roll': dict(sign=1, offset_degrees=90+math.degrees(.0486795+math.pi-3.14)),
        }, gripper_closed_rad=-.21, gripper_open_rad=1.5,
        assumptions=['Gripper percentage normalizes simulation limits; no contact physics.',
                     'SO100 and SO101 distal link dimensions differ; matching axes is not identical tool position.'])


def load_mapping(target, path=None, *, replay=False):
    if path is None:
        if replay:
            raise ValueError('Replay requires --mapping from the recorded run')
        if target == 'sim':
            return simulation_mapping()
        path = Path.home() / '.config/worldcompute/so100-mapping.json'
    mapping = json.loads(Path(path).read_text())
    if not replay and target == 'sim' and mapping.get('target') != 'sim':
        raise ValueError('Simulation requires a simulation mapping, not a physical station calibration')
    if not replay and target == 'robot' and mapping.get('target') == 'sim':
        raise ValueError('Simulation mapping cannot be used for the physical robot')
    return mapping
