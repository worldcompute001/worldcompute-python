"""SDK observation and joint control backed by the local World Compute playground."""
import asyncio
import base64
import io
import json
import os
import time
import tempfile
from pathlib import Path
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import uuid4

import httpx


class PlaygroundSim:
    mode = 'simulation'

    async def __aenter__(self):
        from playwright.async_api import async_playwright

        self.driver = await async_playwright().start()
        try:
            self.browser = await self.driver.chromium.launch(channel='chrome',
                args=['--enable-unsafe-swiftshader'])
            self.page = await self.browser.new_page()
            origin = os.environ.get('WC_SIM_ORIGIN', 'http://127.0.0.1:18835').rstrip('/')
            async with httpx.AsyncClient() as client:
                response = await client.get(origin + '/backend')
                response.raise_for_status()
                state = response.json()['state']
            if state['mode'] != self.mode or state['robot_id'] != 'so100':
                raise ValueError('Expected a World Compute SO100 simulation')
            self.joints = state['joints']
            self.origin = origin
            token = os.environ.get('WC_SIM_TOKEN', '')
            if not token and origin == 'http://127.0.0.1:18835':
                token = (Path(tempfile.gettempdir()) / 'wc-sim-run-key').read_text().strip()
            self.http = httpx.AsyncClient(base_url=origin, timeout=5,
                headers={'Authorization':'Bearer '+token})
            await self.page.goto(origin + '/playground?sdk=1')
            await self.page.wait_for_function("typeof window.wcSimObservation === 'function'")
        except BaseException:
            await self.driver.stop()
            raise
        return self

    async def __aexit__(self, *_):
        try:
            await self.http.aclose()
            await self.browser.close()
        finally:
            await self.driver.stop()

    @asynccontextmanager
    async def observation_stream(self):
        from PIL import Image
        latest = {}
        async def capture():
            while True:
                pose = (await self.state())['joints']
                stamp = time.time()
                encoded = await self.page.evaluate('(p) => window.wcSimObservation(p)', pose)
                cameras = []
                for name, data in encoded.items():
                    with Image.open(io.BytesIO(base64.b64decode(data))) as image:
                        cameras.append(dict(track_name=name, width=image.width, height=image.height,
                            captured_at_us=int(stamp * 1e6), rgb=image.convert('RGB').tobytes()))
                latest.update(robot_state={'payload': self._state(pose, stamp)}, cameras=cameras)
                await asyncio.sleep(.1)

        def read(**_):
            if task.done():
                task.result()
            return latest or {'robot_state': None, 'cameras': []}

        task = asyncio.create_task(capture())
        try:
            yield read
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def observe(self, *, timeout=15):
        async with asyncio.timeout(timeout), self.observation_stream() as read:
            while not (snapshot := read())['cameras']:
                await asyncio.sleep(.05)
            return snapshot

    def _state(self, joints, stamp):
        return dict(robot_id='so100', mode=self.mode, unit='rad', joints=dict(joints),
                    observed_at=datetime.fromtimestamp(stamp, timezone.utc).isoformat())

    async def state(self):
        response = await self.http.get('/backend')
        response.raise_for_status()
        self.joints = response.json()['state']['joints']
        return self._state(self.joints, time.time())

    def station_time_bounds(self):
        now = time.time()
        return now, now

    @asynccontextmanager
    async def robot(self, robot_id, *, mode):
        if (robot_id, mode) != ('so100', self.mode):
            raise ValueError('This backend only supports the simulated SO100')
        self.last_request = None
        yield self

    async def target(self, values):
        import math
        if not values or not values.keys() <= self.joints.keys() or not all(math.isfinite(v) for v in values.values()):
            raise ValueError('Invalid simulated joint target')
        target = dict((await self.state())['joints'], **values)
        response = await self.http.post('/sim-target', json=target)
        if response.status_code == 422:
            from .session import ControlsError
            raise ControlsError('Simulation controller rejected move: '+response.json()['error'])
        response.raise_for_status()
        self.joints = response.json()['joints']
        self.last_request = str(uuid4())
        print('Sim pose ' + json.dumps(self.joints), flush=True)
        return self.last_request

    async def wait(self, request, *, timeout=10):
        if request != self.last_request:
            raise ValueError('Unknown simulation request')
        return {'state': 'completed'}

    async def hold(self):
        pass  # Kinematic joints stay at their last target.
