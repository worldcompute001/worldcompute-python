from datetime import datetime, timezone
import time
import pytest

from worldcompute.harness import paired


def test_pair_requires_distinct_fresh_synchronized_views():
    now = time.time_ns() // 1000
    cameras = [dict(track_name=name, captured_at_us=now) for name in ('overhead', 'arm')]
    snapshot = dict(cameras=cameras, robot_state=dict(payload=dict(robot_id='so100',
        unit='rad', observed_at=datetime.now(timezone.utc).isoformat(), joints={'shoulder_pan': 0})))
    assert set(paired(snapshot)[0]) == {'overhead', 'arm'}
    cameras[1]['captured_at_us'] -= 300_000
    assert paired(snapshot) is None
    cameras[1]['track_name'] = 'overhead'
    with pytest.raises(ValueError, match='Ambiguous'):
        paired(snapshot)
