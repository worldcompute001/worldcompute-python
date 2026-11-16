import json
import pytest
from worldcompute import RobotSession, ControlsError, OutcomeUnknown

class Participant:
    def __init__(self): self.calls=[]; self.fail=False
    async def perform_rpc(self, **kwargs):
        p=json.loads(kwargs['payload']);self.calls.append(p)
        if self.fail: raise TimeoutError()
        body={'state':'dispatched', 'stream_id':'stream'}
        if p['operation']=='state': body={'executions':{'id':{'state':'completed'}}}
        return json.dumps({'status':200,'body':body})
    async def publish_data(self,*args,**kwargs):self.calls.append(kwargs)

def session(p): return RobotSession(p,'station',{'session_id':'s','mode':'simulation','robot_id':'arm'})

async def test_measured_completion_cleanup():
    p=Participant()
    async with session(p) as s:
        assert await s.reset(request_id='id')=='id'
        assert (await s.wait('id'))['state']=='completed'
    assert p.calls[-1]['operation']=='stop'
    with pytest.raises(ControlsError):await s.reset()

async def test_unknown_never_retried():
    p=Participant();p.fail=True;s=session(p)
    with pytest.raises(OutcomeUnknown) as error:await s.reset(request_id='original')
    assert error.value.request_id=='original';assert len(p.calls)==1

async def test_hold_invalidates_stream():
    p=Participant();s=session(p)
    await s.jog({'elbow':.1});await s.publish_jog({'elbow':0})
    await s.hold()
    with pytest.raises(ControlsError):await s.publish_jog({'elbow':.1})

async def test_failed_renewal_blocks_commands_but_allows_stop():
    p=Participant();s=session(p);s.failure=TimeoutError()
    with pytest.raises(ControlsError):await s.reset()
    await s.stop()
