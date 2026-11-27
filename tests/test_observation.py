import asyncio
import json
from types import SimpleNamespace as S

import pytest
from livekit import rtc
from worldcompute.observation import snapshot


class Room:
    def __init__(self):
        self.handlers = {}
        self.disconnected = False

    def on(self, event, callback):
        self.handlers[event] = callback

    async def connect(self, *args):
        self.handlers['track_subscribed'](S(kind=rtc.TrackKind.KIND_VIDEO),
            S(sid='video-1', name='wrist'), S(identity='camera:so100'))
        packet = S(topic='wc.canary.state.v1', participant=S(identity='canary:station'),
            data=json.dumps({'joints': {'gripper': .2}}).encode())
        self.handlers['data_received'](packet)
        packet.participant = S(identity='untrusted')
        packet.data = b'{"joints": {"gripper": 999}}'
        self.handlers['data_received'](packet)

    async def disconnect(self):
        self.disconnected = True


class VideoStream:
    def __init__(self, *args, **kwargs):
        self.first = True

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.first:
            self.first = False
            return S(frame=S(width=1, height=1, data=b'\x01\x02\x03'),
                metadata=S(user_timestamp=123))
        await asyncio.Future()

    async def aclose(self):
        pass


@pytest.mark.asyncio
async def test_view_only_snapshot_retains_sources_and_disconnects(monkeypatch):
    monkeypatch.setattr(rtc, 'VideoStream', VideoStream)
    room = Room()
    requests = []

    async def request(method, path, body):
        requests.append(path)
        return {'url': 'wss://live', 'token': 'token'}

    result = await snapshot(S(room_factory=lambda: room, _request=request), timeout=.15)
    assert requests == ['/api/sdk/v1/live-token']
    assert result['robot_state']['payload']['joints']['gripper'] == .2
    assert result['cameras'][0]['captured_at_us'] == 123
    assert result['cameras'][0]['rgb'] == b'\x01\x02\x03'
    assert result['cameras'][0]['participant'] == 'camera:so100'
    assert room.disconnected


@pytest.mark.asyncio
async def test_cancel_observation_disconnects(monkeypatch):
    monkeypatch.setattr(rtc, 'VideoStream', VideoStream)
    room = Room()

    async def request(*args):
        return {'url': 'wss://live', 'token': 'token'}

    task = asyncio.create_task(snapshot(S(room_factory=lambda: room, _request=request)))
    await asyncio.sleep(.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert room.disconnected
