"""Standalone HTTP admission and LiveKit transport; never direct motor access."""
import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from urllib.parse import urlparse
import httpx
from .session import RobotSession, ControlsError


class WorldCompute:
    def __init__(self, *, base_url='https://worldcompute.org', access_token=None, http=None, room_factory=None):
        url = urlparse(base_url)
        if url.scheme != 'https' or url.username or url.password or url.query or url.fragment or url.path not in ('', '/'):
            raise ValueError('base_url must be an HTTPS origin')
        self.base_url = base_url.rstrip('/')
        self.access_token = access_token or os.environ.get('WC_ACCESS_TOKEN')
        self._refresh_token = None
        self._expires = 0
        self._refresh_lock = asyncio.Lock()
        self.http = http or httpx.AsyncClient(base_url=self.base_url, timeout=10, follow_redirects=False)
        self._owns_http = http is None
        self.room_factory = room_factory

    async def login(self, *, physical=False, open_browser=True):
        from .login import authorize
        tokens = await authorize(self.http, self.base_url, physical=physical, open_browser=open_browser)
        self._set_tokens(tokens)
        return self

    def _set_tokens(self, tokens):
        self.access_token = tokens['access_token']
        self._refresh_token = tokens.get('refresh_token', self._refresh_token)
        self._expires = time.monotonic() + tokens.get('expires_in', 900)

    async def _credentials(self):
        async with self._refresh_lock:
            if self._refresh_token and time.monotonic() >= self._expires - 60:
                response = await self.http.post('/oauth/token', data={
                    'grant_type':'refresh_token', 'refresh_token':self._refresh_token,
                    'client_id':'world-compute-python', 'resource':self.base_url+'/mcp'})
                if response.status_code != 200:
                    raise ControlsError('Login expired; authenticate again')
                self._set_tokens(response.json())
        if not self.access_token:
            raise ControlsError('Call await wc.login() or provide WC_ACCESS_TOKEN')
        return {'Authorization':'Bearer '+self.access_token}

    async def _request(self, method, path, body=None):
        response = await self.http.request(method, path, headers=await self._credentials(), json=body)
        if not response.is_success:
            raise ControlsError(f'World Compute HTTP {response.status_code}: request rejected; do not replay motion automatically')
        return response.json()

    async def robots(self):
        return (await self._request('GET', '/api/sdk/v1/robots'))['robots']

    @asynccontextmanager
    async def robot(self, robot_id, *, mode='simulation'):
        from uuid import uuid4
        from urllib.parse import quote
        if mode not in ('simulation', 'physical'):
            raise ValueError('mode must be simulation or physical')
        if self.room_factory is None:
            from livekit import rtc
            room = rtc.Room()
        else:
            room = self.room_factory()
        session = None
        try:
            live = await self._request('POST', '/api/sdk/v1/live-token', {})
            await room.connect(live['url'], live['token'])
            admission = await self._request('POST', '/api/sdk/v1/robots/'+quote(robot_id,safe='')+'/sessions', {
                'request_id':str(uuid4()), 'mode':mode, 'identity':live['identity'], 'binding':live['binding']})
            created = json.loads(await room.local_participant.perform_rpc(
                destination_identity=admission['station'], method='wc.controls.v1',
                payload=json.dumps({'ticket':admission['ticket']}), response_timeout=5))
            if created['status'] not in (200,201):
                raise ControlsError('Session creation rejected')
            body = created['body']
            if body['robot_id'] != robot_id or body['mode'] != mode:
                raise ControlsError('Session identity mismatch; command not sent')
            session = RobotSession(room.local_participant, admission['station'], body, created.get('server_time'))
            # Prevent continued input after disconnect; never reconnect/replay automatically.
            if hasattr(room, 'on'):
                room.on('disconnected', lambda *args: setattr(session, 'failure', ControlsError('LiveKit disconnected')))
            async with session:
                yield session
        finally:
            await room.disconnect()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        if self._owns_http:
            await self.http.aclose()
