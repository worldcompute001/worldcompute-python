import json
import asyncio
import httpx
import pytest
from worldcompute import WorldCompute, ControlsError

class Room:
    def __init__(self): self.remote_participants={"canary:station":object()};self.local_participant=self;self.calls=[];self.disconnected=False
    async def connect(self,*args): pass
    async def disconnect(self):self.disconnected=True
    async def perform_rpc(self,**kwargs):
        p=json.loads(kwargs['payload']);self.calls.append(p)
        if 'ticket' in p:body={'session_id':'s','mode':'simulation','robot_id':'arm'}
        elif p['operation']=='state':body={'executions':{'id':{'state':'completed'}}}
        else:body={'state':'dispatched'}
        return json.dumps({'status':200,'body':body})

async def test_standalone_admission_and_cleanup():
    requests=[];room=Room()
    room.remote_participants.clear()
    asyncio.get_running_loop().call_later(.15, lambda: room.remote_participants.update({"canary:station":object()}))
    def respond(req):
        requests.append(req)
        assert req.headers['authorization']=='Bearer token'
        if req.url.path.endswith('/live-token'):data={'url':'wss://live','token':'live','identity':'i','binding':'b'}
        elif req.url.path.endswith('/sessions'):
            assert 'canary:station' in room.remote_participants
            assert json.loads(req.content)['mode']=='simulation'
            data={'ticket':'t','station':'station'}
        else:data={'robots':[{'id':'arm'}]}
        return httpx.Response(200,json=data)
    async with httpx.AsyncClient(base_url='https://wc.test',transport=httpx.MockTransport(respond)) as http:
        async with WorldCompute(base_url='https://wc.test',access_token='token',http=http,room_factory=lambda:room) as wc:
            assert await wc.robots()==[{'id':'arm'}]
            async with wc.robot('arm') as arm:
                await arm.reset(request_id='id');assert (await arm.wait('id'))['state']=='completed'
    assert room.calls[-1]['operation']=='stop';assert room.disconnected
    assert len(requests)==3

async def test_rejected_admission_disconnects_without_commands():
    room=Room()
    def respond(req):
        return httpx.Response(200,json={'url':'wss://live','token':'live','identity':'i','binding':'b'}) if req.url.path.endswith('/live-token') else httpx.Response(403)
    async with httpx.AsyncClient(base_url='https://wc.test',transport=httpx.MockTransport(respond)) as http:
        wc=WorldCompute(base_url='https://wc.test',access_token='t',http=http,room_factory=lambda:room)
        with pytest.raises(ControlsError):
            async with wc.robot('arm'):pass
    assert room.disconnected;assert room.calls==[]

def test_reject_insecure_or_credentialed_origin():
    for url in ['http://example.com','https://user:pass@example.com','https://example.com/path']:
        with pytest.raises(ValueError):WorldCompute(base_url=url)
