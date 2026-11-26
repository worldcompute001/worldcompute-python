"""Save the live WC camera inputs and station telemetry for a model preview."""
import argparse
import asyncio
import json
from pathlib import Path

from worldcompute import WorldCompute


async def capture(output, seconds):
    if output.exists():
        raise FileExistsError(f'Output already exists: {output}')
    async with WorldCompute() as wc:
        if not wc.access_token:
            await wc.login()
        observation = await wc.observe(timeout=seconds)
    output.mkdir(parents=True, exist_ok=False)
    for index, camera in enumerate(observation['cameras']):
        filename = f'camera-{index}.ppm'
        pixels = camera.pop('rgb')
        header = f"P6\n{camera['width']} {camera['height']}\n255\n".encode()
        (output / filename).write_bytes(header + pixels)
        camera['file'] = filename
    (output / 'observation.json').write_text(json.dumps(observation, indent=2) + '\n')
    print(f"Saved {len(observation['cameras'])} camera views to {output.resolve()}")
    print('Station telemetry received:', observation['robot_state'] is not None)
    for camera in observation['cameras']:
        print(camera['file'], camera['participant'], camera['track_name'], camera['track_sid'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=float, default=15)
    args = parser.parse_args()
    asyncio.run(capture(args.output, args.seconds))
