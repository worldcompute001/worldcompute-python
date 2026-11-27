"""The existing wc.controls.v1 contract, without HTTP or hardware ownership."""
import asyncio
import json
import math
import time
from datetime import datetime, timezone
from uuid import uuid4


class ControlsError(RuntimeError):
    pass


class OutcomeUnknown(ControlsError):
    def __init__(self, request_id):
        self.request_id = request_id
        super().__init__(f'Outcome unconfirmed for {request_id}; inspect state before another command')


class RobotSession:
    def __init__(self, participant, station, created, server_time=None, *, clock_window=None):
        self.participant, self.station = participant, station
        self.id, self.mode = created['session_id'], created['mode']
        self.robot_id = created['robot_id']
        self._server_time = server_time
        self._clock_window = clock_window
        self.offset = (server_time - time.time()) if server_time else 0
        self.closed = False
        self.failure = None
        self.sequence = 0
        self.stream_id = None
        self.stream_kind = None
        self._renewal = None

    def station_time_bounds(self):
        """Bound station UTC using its admission response and local monotonic elapsed time."""
        if (self._clock_window is None or type(self._server_time) not in (int, float)
                or not math.isfinite(self._server_time) or self._server_time <= 0):
            raise ControlsError('Missing valid station clock sample')
        sent, received = self._clock_window
        now = time.monotonic()
        return self._server_time + (now - received), self._server_time + (now - sent)

    async def _rpc(self, operation, body=None):
        if self.closed:
            raise ControlsError('Session closed')
        if self.failure and operation not in ('state', 'hold', 'stop'):
            raise ControlsError('Session renewal failed; reconnect deliberately') from self.failure
        raw = await self.participant.perform_rpc(destination_identity=self.station,
            method='wc.controls.v1', payload=json.dumps({'session_id': self.id,
            'operation': operation, 'body': body or {}}), response_timeout=3)
        result = json.loads(raw)
        if result['status'] != 200:
            raise ControlsError(result.get('body', {}).get('error', 'Request rejected'))
        return result['body']

    def _packet(self, action, request_id, lifetime=1):
        packet = {'request_id': request_id, 'action': action}
        if action['type'] in ('joint_follow', 'joint_jog'):
            self.sequence += 1
            packet.update(sequence=self.sequence, expires_at=datetime.fromtimestamp(
                time.time()+self.offset+lifetime, timezone.utc).isoformat())
        return packet

    async def command(self, action, *, request_id=None):
        request_id = request_id or str(uuid4())
        try:
            result = await self._rpc('commands', self._packet(action, request_id))
        except ControlsError:
            raise
        except Exception as error:
            raise OutcomeUnknown(request_id) from error
        if result.get('state') != 'dispatched':
            raise ControlsError(result.get('reason', 'Command rejected'))
        self.stream_id = result.get('stream_id')
        self.stream_kind = action['type']
        return request_id

    async def target(self, positions, *, request_id=None):
        return await self.command({'type': 'joint_target', 'positions': positions}, request_id=request_id)

    async def sequence_targets(self, waypoints, *, request_id=None):
        return await self.command({'type': 'joint_sequence', 'waypoints': waypoints}, request_id=request_id)

    async def follow(self, positions):
        return await self.command({'type': 'joint_follow', 'positions': positions})

    async def jog(self, velocities):
        return await self.command({'type': 'joint_jog', 'velocities': velocities})

    async def publish_jog(self, velocities):
        if self.closed or self.failure or not self.stream_id or self.stream_kind != 'joint_jog':
            raise ControlsError('Initialize a healthy jog session first')
        command = self._packet({'type': 'joint_jog', 'velocities': velocities}, str(uuid4()), .3)
        await self.participant.publish_data(json.dumps({'session_id': self.id, 'operation': 'inputs',
            'body': {'stream_id': self.stream_id, 'command': command}}).encode(),
            reliable=False, topic='wc.controls.input.v1', destination_identities=[self.station])

    async def reset(self, *, request_id=None):
        return await self.command({'type': 'reset'}, request_id=request_id)

    async def state(self):
        return await self._rpc('state')

    async def wait(self, request_id, *, timeout=30):
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            result = (await self.state()).get('executions', {}).get(request_id)
            if result:
                if result['state'] == 'completed':
                    return result
                if result['state'] not in ('pending', 'running', 'dispatched'):
                    raise ControlsError(f'Execution {request_id} ended: {result["state"]}')
            await asyncio.sleep(.1)
        raise OutcomeUnknown(request_id)

    async def renew(self):
        return await self._rpc('renew')

    async def hold(self):
        self.stream_id = None
        result = await self._rpc('hold')
        if result.get('state') != 'dispatched':
            raise ControlsError('Hold unconfirmed')
        return result

    async def stop(self):
        if self.closed:
            return
        self.stream_id = None
        try:
            result = await self._rpc('stop')
            if result.get('state') != 'dispatched':
                raise ControlsError('Stop unconfirmed')
        finally:
            self.closed = True

    async def _renew_loop(self):
        try:
            while not self.closed:
                await asyncio.sleep(2)
                await self.renew()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.failure = error
            self.stream_id = None
            try:
                await self.hold()
            except Exception:
                pass  # Never report an unconfirmed hold as success.

    async def __aenter__(self):
        if self.closed or self._renewal:
            raise ControlsError('Session cannot be entered twice')
        self._renewal = asyncio.create_task(self._renew_loop())
        return self

    async def __aexit__(self, *exc):
        self._renewal.cancel()
        try:
            await self._renewal
        except asyncio.CancelledError:
            pass
        await self.stop()
