import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from worldcompute.trace import Trace
from worldcompute.molmo import predict
from worldcompute.playground_sim import PlaygroundSim
from worldcompute.session import ControlsError
from worldcompute.so101_mapping import JOINTS, model_state, wc_targets


def test_mapping_roundtrip_and_prediction_evidence(tmp_path):
    np = pytest.importorskip('numpy')
    pytest.importorskip('dreamscale')
    mapping = dict(joints={n: dict(sign=-1 if i % 2 else 1, offset_degrees=7*i)
                          for i, n in enumerate(JOINTS)},
                   gripper_closed_rad=.1, gripper_open_rad=2.)
    joints = dict(zip((*JOINTS, 'gripper'), [.1, -.2, .3, -.4, .5, .9]))
    assert wc_targets([model_state(joints, mapping)], mapping)[0] == pytest.approx(joints)
    rows = np.tile(model_state(joints, mapping), (30, 1))
    rows[5, 5] = 105
    session = SimpleNamespace(predict=lambda *a, **kw: SimpleNamespace(actions=rows))
    camera = dict(rgb=bytes([10, 20, 30]), width=1, height=1, captured_at_us=123)
    directory = tmp_path / 'trace'
    with Trace(directory):
        targets = asyncio.run(asyncio.to_thread(predict, session, 'move', mapping,
                              dict(overhead=camera, arm=camera), joints, task=True))
    events = [json.loads(line) for line in (directory/'events.jsonl').read_text().splitlines()]
    assert [e['event'] for e in events] == ['observation', 'prediction', 'conversion']
    assert events[1]['actions'][5][5] == 105
    assert events[2]['selected_model_actions'][0][5] == 100
    assert events[2]['gripper_clipped'] is True
    assert targets['gripper'] == 2
    assert (directory/'0001-arm.png').is_file()
    assert (directory/'0001-overhead.png').is_file()
    with pytest.raises(FileExistsError):
        Trace(directory)


async def test_controller_rejection_recorded_without_mutating_sdk_state(tmp_path):
    initial = dict.fromkeys((*JOINTS, 'gripper'), 0.)
    reason = dict(code='joint_limit', joint='elbow_flex', error='outside bounds', target=2, min=-1, max=1.4)
    def respond(request):
        if request.method == 'GET':
            return httpx.Response(200, json={'state': {'joints': initial}})
        return httpx.Response(422, json=reason)
    sim = PlaygroundSim()
    sim.joints = initial.copy()
    async with httpx.AsyncClient(base_url='http://sim', transport=httpx.MockTransport(respond)) as client:
        sim.http = client
        with Trace(tmp_path/'trace'):
            with pytest.raises(ControlsError, match='outside bounds'):
                await sim.target({'elbow_flex': 2})
    assert sim.joints == initial
    event = json.loads((tmp_path/'trace/events.jsonl').read_text())
    assert event['event'] == 'controller_rejected'
    assert event['reason'] == reason
