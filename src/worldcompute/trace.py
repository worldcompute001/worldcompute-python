"""Opt-in local experiment artifacts. Never records credentials or transport headers."""
from contextvars import ContextVar
from pathlib import Path
import json
import threading
import time

_active = ContextVar('wc_trace', default=None)


class Trace:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False, mode=0o700)
        self.lock = threading.Lock()
        self.predictions = 0

    def __enter__(self):
        self.token = _active.set(self)
        return self

    def __exit__(self, *_):
        _active.reset(self.token)

    def event(self, kind, **values):
        with self.lock:
            with (self.directory / 'events.jsonl').open('a') as output:
                output.write(json.dumps(dict(event=kind, at=time.time(), **values), allow_nan=False) + '\n')


def event(kind, **values):
    if trace := _active.get():
        trace.event(kind, **values)


def observation(views, joints, model_joints):
    if not (trace := _active.get()):
        return
    from PIL import Image
    trace.predictions += 1
    cameras = {}
    for name, camera in views.items():
        filename = f'{trace.predictions:04d}-{name}.png'
        Image.frombytes('RGB', (camera['width'], camera['height']), camera['rgb']).save(trace.directory / filename)
        cameras[name] = dict(file=filename, width=camera['width'], height=camera['height'],
                             captured_at_us=camera.get('captured_at_us'))
    snapshot = dict(robot_state={'payload': {'robot_id': 'so100', 'unit': 'rad', 'joints': joints}},
                    cameras=[dict(track_name=name, **camera) for name, camera in cameras.items()])
    (trace.directory / f'{trace.predictions:04d}-observation.json').write_text(json.dumps(snapshot, indent=2))
    trace.event('observation', prediction=trace.predictions, cameras=cameras,
                joints_rad=joints, model_joints=model_joints)
