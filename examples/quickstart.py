"""Run from your own computer. Defaults to the remote simulated twin."""
import argparse
import asyncio
from worldcompute import WorldCompute

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--robot', help='Registered robot ID; otherwise use the first listed robot')
    parser.add_argument('--base-url', default='https://worldcompute.org')
    parser.add_argument('--physical', action='store_true', help='Command real hardware (requires attended clearance)')
    parser.add_argument('--no-browser', action='store_true', help='Print login URL instead of opening it')
    args = parser.parse_args()
    if args.physical and input('Physical reset moves the arm. Operator present and path clear? Type RESET: ') != 'RESET':
        raise SystemExit('Cancelled; no connection or command sent')
    async with WorldCompute(base_url=args.base_url) as wc:
        if not wc.access_token:
            await wc.login(physical=args.physical, open_browser=not args.no_browser)
        robots = await wc.robots()
        if not robots:
            raise SystemExit('No robots available to this account')
        robot_id = args.robot or robots[0]['id']
        mode = 'physical' if args.physical else 'simulation'
        print(f'Connecting to {robot_id} in {mode} mode')
        async with wc.robot(robot_id, mode=mode) as robot:
            request_id = await robot.reset()
            print('Accepted request:', request_id)
            result = await robot.wait(request_id)
            print('Measured completion:', result)
        print('Session stopped and released')

if __name__ == '__main__':
    asyncio.run(main())
