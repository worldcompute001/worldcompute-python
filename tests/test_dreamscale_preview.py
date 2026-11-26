import importlib.util
from pathlib import Path
import math
import pytest

spec = importlib.util.spec_from_file_location('preview', Path(__file__).parents[1] / 'examples/dreamscale_preview.py')
preview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preview)


def test_round_trip_preserves_joint_conventions_and_gripper():
    mapping = {'joints': {name: {'sign': -1, 'offset_degrees': 30} for name in preview.JOINTS},
               'gripper_closed_rad': .8, 'gripper_open_rad': -.2}
    joints = dict.fromkeys(preview.JOINTS, .4)
    joints['gripper'] = .3
    state = preview.model_state(joints, mapping)
    assert state[0] == pytest.approx(30 - math.degrees(.4))
    assert state[5] == pytest.approx(50)
    assert preview.wc_targets([state], mapping)[0] == pytest.approx(joints)
    joints['gripper'] = 1.2
    with pytest.raises(ValueError, match='outside'):
        preview.model_state(joints, mapping)
    with pytest.raises(ValueError):
        preview.wc_targets([[0, 0, 0, 0, 0, 101]], mapping)
