import asyncio
from datetime import datetime, timezone
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from worldcompute.task_rollout import rollout

async def test_replans_and_cancels_without_replaying():
    joints = dict.fromkeys(('shoulder_pan','shoulder_lift','elbow_flex','wrist_roll','wrist_flex','gripper'), 0.)
    def latest():
        return dict(cameras=[dict(track_name=n,captured_at_us=time.time_ns()//1000)
                             for n in ('overhead','arm')],
                    robot_state=dict(payload=dict(robot_id='so100', unit='rad', joints=joints.copy(),
                        observed_at=datetime.now(timezone.utc).isoformat())))
    def policy(views, measured):
        return {k:v+.1 for k,v in measured.items()}
    async def target(values):
        joints.update(values)
        return 'request'
    arm=SimpleNamespace(station_time_bounds=lambda: (time.time(), time.time()), state=AsyncMock(side_effect=lambda:dict(latest()['robot_state']['payload'],mode='physical')),
                        target=AsyncMock(side_effect=target),wait=AsyncMock())
    assert await rollout(policy,latest,arm,2)=='step limit reached'
    assert all(v==pytest.approx(.04) for v in joints.values())
    arm.wait.side_effect=asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await rollout(policy,latest,arm,2)
    assert arm.target.await_count==3


def test_pre_move_diagnostic_reports_all_failures_and_deltas():
    from worldcompute.task_rollout import checked_positions
    state = dict(robot_id='other', mode='simulation', unit='deg',
                 observed_at='2020-01-01T00:00:00+00:00',
                 joints={'elbow': .05, 'gripper': .2})
    with pytest.raises(RuntimeError) as exc:
        checked_positions(state, {'elbow': .08, 'gripper': .2}, (time.time(), time.time()))
    for detail in ("robot_id='other'", "mode='simulation'", "unit='deg'",
                   'timestamp outside', 'controller age=', 'elbow drift exceeds',
                   'elbow=-0.030000', 'gripper=+0.000000'):
        assert detail in str(exc.value)

def test_station_clock_controls_both_freshness_boundaries():
    from worldcompute.task_rollout import checked_positions
    stamp = 1_800_000_000
    state = dict(robot_id='so100', unit='rad', mode='physical', joints={'elbow': 0},
                 observed_at=datetime.fromtimestamp(stamp, timezone.utc).isoformat())
    assert checked_positions(state, state['joints'], (stamp+.01, stamp+.06)) == state['joints']
    for bounds in [(stamp-.01, stamp+.06), (stamp+1.95, stamp+2)]:
        with pytest.raises(RuntimeError, match='timestamp outside'):
            checked_positions(state, state['joints'], bounds)


async def test_expired_prediction_replanned_and_transient_gap_waited(monkeypatch):
    from worldcompute import task_rollout
    now = time.time()
    calls = []
    reads = 0

    def latest():
        nonlocal reads
        reads += 1
        return dict(cameras=[] if reads == 3 else [
            dict(track_name=n, captured_at_us=int(now * 1e6)) for n in ('overhead', 'arm')],
            robot_state=dict(payload=dict(robot_id='so100', unit='rad', joints={'elbow': 0.},
                observed_at=datetime.now(timezone.utc).isoformat())))

    def policy(views, measured):
        nonlocal now
        calls.append(views['arm']['captured_at_us'])
        if len(calls) == 1:
            now += 6
        return {'elbow': len(calls) * .005}

    monkeypatch.setattr(task_rollout.time, 'time', lambda: now)
    arm = SimpleNamespace(target=AsyncMock(return_value='request'), wait=AsyncMock(), state=AsyncMock(
        return_value={'joints': {'elbow': .01}}))
    monkeypatch.setattr(task_rollout, 'controller_positions', AsyncMock(return_value={'elbow': 0.}))
    assert await rollout(policy, latest, arm, 1) == 'step limit reached'
    assert calls[1] > calls[0]
    arm.target.assert_awaited_once_with({'elbow': .01})


async def test_tracking_waits_for_late_elbow_and_reports_stall(monkeypatch):
    from worldcompute import task_rollout
    arm = SimpleNamespace(state=AsyncMock(side_effect=[
        {'joints': {'elbow': 0.}}, {'joints': {'elbow': .018}}]))
    assert await task_rollout.wait_for_tracking(arm, {'elbow': .02}) == {'elbow': .018}
    arm.state = AsyncMock(return_value={'joints': {'elbow': 0.}})
    with pytest.raises(RuntimeError, match='elbow'):
        await task_rollout.wait_for_tracking(arm, {'elbow': .02})


async def test_segment_preserves_order_and_total_budget(monkeypatch):
    from worldcompute import task_rollout
    arm = SimpleNamespace(target=AsyncMock(), wait=AsyncMock())
    monkeypatch.setattr(task_rollout, 'observe_after', AsyncMock(return_value=(
        {'arm': {'captured_at_us': time.time()*1e6}}, {'elbow': 0.})))
    monkeypatch.setattr(task_rollout, 'check_pair', lambda _: (True, None))
    monkeypatch.setattr(task_rollout, 'controller_positions', AsyncMock(side_effect=lambda a, m: m))
    monkeypatch.setattr(task_rollout, 'wait_for_tracking', AsyncMock(side_effect=lambda a, t: t))
    policy = lambda *_: [{'elbow': .01}, {'elbow': .022}, {'elbow': .035}]
    assert await rollout(policy, lambda: {}, arm, 2) == 'step limit reached'
    assert [call.args[0]['elbow'] for call in arm.target.await_args_list] == [.01, .022]


async def test_task_duration_and_inner_timeout(monkeypatch):
    from worldcompute import task_rollout
    async def slow(*args):
        await asyncio.sleep(10)
    monkeypatch.setattr(task_rollout, 'rollout', slow)
    assert await task_rollout.timed_rollout(None, None, None, 1, .01) == 'time limit reached'
    monkeypatch.setattr(task_rollout, 'rollout', AsyncMock(side_effect=TimeoutError('camera timeout')))
    with pytest.raises(TimeoutError, match='camera timeout'):
        await task_rollout.timed_rollout(None, None, None, 1, 5)
