from types import SimpleNamespace

import pytest

from worldcompute.molmo import predict
from worldcompute.so101_mapping import JOINTS


def test_shoulder_only_prediction_ignores_unused_gripper():
    np = pytest.importorskip('numpy')
    pytest.importorskip('dreamscale')
    rows = np.zeros((30, 6))
    rows[0, 0], rows[0, 5] = 15, 101
    camera = dict(rgb=bytes(3), width=1, height=1)
    mapping = dict(joints={n: dict(sign=-1, offset_degrees=5) for n in JOINTS},
                   gripper_closed_rad=0, gripper_open_rad=1)
    session = SimpleNamespace(predict=lambda *a, **kw: SimpleNamespace(actions=rows))
    args = (session, 'turn', mapping, dict(overhead=camera, arm=camera),
            dict.fromkeys((*JOINTS, 'gripper'), 0.0))
    assert predict(*args) == pytest.approx(np.deg2rad(-10))
    rows[0, 0] = np.nan
    with pytest.raises(ValueError, match='finite'):
        predict(*args)


def test_sim_target_cannot_open_a_physical_session():
    import asyncio
    from worldcompute.client import WorldCompute
    from worldcompute.playground_sim import PlaygroundSim

    async def check():
        sim = WorldCompute.for_target('sim')
        assert isinstance(sim, PlaygroundSim)
        with pytest.raises(ValueError, match='simulated SO100'):
            async with sim.robot('so100', mode='physical'):
                pytest.fail('unexpected physical session')
        with pytest.raises(ValueError, match='target must be'):
            WorldCompute.for_target('typo')

    asyncio.run(check())
