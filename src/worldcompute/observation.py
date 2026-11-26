"""Read camera frames and station telemetry through the existing viewing connection."""
from contextlib import asynccontextmanager
import asyncio
import json
import time

from .session import ControlsError


@asynccontextmanager
async def observation_stream(wc, *, timeout=15):
    from livekit import rtc

    room = wc.room_factory() if wc.room_factory else rtc.Room()
    frames, tasks = {}, []
    synchronized = None
    state = None
    disconnected = False
    station = None

    async def receive(track, publication, participant):
        nonlocal synchronized
        stream = rtc.VideoStream(track, capacity=1, format=rtc.VideoBufferType.RGB24)
        key = participant.identity + '/' + publication.sid
        try:
            async for event in stream:
                captured = getattr(event.metadata, 'user_timestamp', None)
                count = frames.get(key, {}).get('frames_received', 0) + 1
                frames[key] = {
                    'frames_received': count,
                    'participant': participant.identity,
                    'track_sid': publication.sid,
                    'track_name': publication.name,
                    'width': event.frame.width,
                    'height': event.frame.height,
                    'rgb': bytes(event.frame.data),
                    'captured_at_us': captured or None,
                    'received_at_ns': time.time_ns(),
                }
                candidates = [c for c in frames.values() if c['track_name'] in ('overhead', 'arm')]
                if len(candidates) == 2 and candidates[0]['track_name'] != candidates[1]['track_name']:
                    first, second = (c['captured_at_us'] for c in candidates)
                    if first and second and abs(first - second) <= 200_000:
                        synchronized = candidates
                else:
                    synchronized = None
        finally:
            await stream.aclose()

    def subscribed(track, publication, participant):
        if track.kind == rtc.TrackKind.KIND_VIDEO:
            tasks.append(asyncio.create_task(receive(track, publication, participant)))

    def telemetry(packet):
        nonlocal state
        if (packet.topic != 'wc.canary.state.v1' or packet.participant is None
                or packet.participant.identity != station or len(packet.data) > 1_000_000):
            return
        try:
            value = json.loads(packet.data)
        except (ValueError, UnicodeDecodeError):
            return
        if isinstance(value, dict):
            state = {'payload': value, 'received_at_ns': time.time_ns()}

    def lost(*args):
        nonlocal disconnected
        disconnected = True

    room.on('track_subscribed', subscribed)
    room.on('data_received', telemetry)
    room.on('disconnected', lost)
    try:
        live = await wc._request('POST', '/api/sdk/v1/live-token', {})
        station = live.get('station', 'canary:station')
        await asyncio.wait_for(room.connect(live['url'], live['token']), timeout)
        def latest(*, synchronized_pair=False):
            if disconnected:
                raise ControlsError('Viewing connection disconnected')
            for task in tasks:
                if task.done() and not task.cancelled() and task.exception():
                    raise ControlsError('Camera reception failed') from task.exception()
            cameras = synchronized if synchronized_pair and synchronized else list(frames.values())
            return {'robot_state': state, 'cameras': cameras,
                    'observed_at_ns': time.time_ns()}

        yield latest
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await room.disconnect()

async def snapshot(wc, *, timeout=15):
    async with observation_stream(wc, timeout=timeout) as latest:
        await asyncio.sleep(timeout)
        result = latest()
        if not result['cameras']:
            raise ControlsError('No camera frames received within the observation window')
        return result
