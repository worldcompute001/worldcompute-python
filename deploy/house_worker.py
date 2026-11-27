"""Run one house-funded SO100 job at a time on the WC workstation."""
import ast
import json
import math
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from house_usage import load_tokenizer, measure, save, subprocess_error, summary
from dreamscale.config import saved_api_key

ROOT = 'https://worldcompute.org/api/harness-worker'


def preview_clearance(lines):
    waypoint = next((line for line in lines if line.startswith('Step 1: {')), None)
    if waypoint is None:
        return 'Table clearance unavailable: no preview waypoint.'
    helper = Path(__file__).resolve().parent / 'table-calibration' / 'waypoint_clearance.py'
    try:
        target = ast.literal_eval(waypoint.partition(': ')[2])
        check = subprocess.run(['/opt/wc-phosphobot-venv/bin/python', str(helper)],
                               input=json.dumps(target, allow_nan=False), capture_output=True,
                               text=True, check=True, timeout=12)
        value = next(line for line in check.stdout.splitlines() if line.startswith('WC_CLEARANCE_MM='))
        mm = float(value.split('=', 1)[1])
        if not math.isfinite(mm):
            raise ValueError('Invalid clearance')
    except (OSError, ValueError, SyntaxError, TypeError, StopIteration, subprocess.SubprocessError):
        return 'Table clearance unavailable: waypoint calculation failed.'
    return (f'Waypoint 1: modeled grasp point {abs(mm):.1f} mm '
            f'{"above" if mm >= 0 else "below"} fitted table (uncalibrated preview).')


def run_job(http, job, tokenizer):
    started = time.monotonic()
    tokens = len(tokenizer.encode(job['prompt'], add_special_tokens=False).ids)
    base = ROOT + '/' + job['id']
    args = [str(Path(sys.executable).with_name('worldcompute')), 'run', 'molmo',
            '--task', '--segment', '--seconds', str(job['seconds']), '--prompt=' + job['prompt']]
    if job['execute']:
        args.append('--execute')
    env = dict(os.environ, WC_ACCESS_TOKEN=job['token'], PYTHONUNBUFFERED='1')
    env.pop('WC_HARNESS_WORKER_KEY', None)
    status, result = 'failed', 'Harness exited before completing the run'
    with tempfile.TemporaryFile() as log, tempfile.TemporaryFile() as metrics:
        check = http.post(base + '/check')
        check.raise_for_status()
        if check.json()['stop']:
            usage = measure(metrics, tokens, time.monotonic() - started)
            save(job['id'], 'cancelled', usage)
            http.post(base + '/finish', json={'status':'cancelled', 'result':summary(usage)}).raise_for_status()
            return
        env['WC_RUN_USAGE_FD'] = str(metrics.fileno())
        child = subprocess.Popen(args, env=env, pass_fds=(metrics.fileno(),), stdout=log, stderr=log, start_new_session=True)
        deadline = time.monotonic() + 145 + job['seconds']
        timed_out = False
        try:
            while child.poll() is None and time.monotonic() < deadline:
                check = http.post(base + '/check')
                check.raise_for_status()
                if check.json()['stop']:
                    status, result = 'cancelled', 'Stop requested'
                    break
                time.sleep(1)
            timed_out = child.poll() is None and status != 'cancelled'
            if child.poll() == 0 and status != 'cancelled':
                log.seek(0)
                lines = log.read().decode(errors='replace').splitlines()
                result = '\n'.join(line for line in lines if line.startswith(('Step ', 'Run ended:')))
                result = result[-2048:]
                if not job['execute']:
                    result += '\n' + preview_clearance(lines)
                status = 'finished'
        except httpx.HTTPError:
            result = 'Workstation lost contact with the queue'
        finally:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGINT)
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
        usage = measure(metrics, tokens, time.monotonic() - started)
        if status == 'failed':
            if timed_out:
                result = 'Worker deadline exceeded'
            elif result == 'Harness exited before completing the run':
                result = subprocess_error(log)
            usage.update(exit_code=child.returncode, error=result)
            result = (f"Last recorded step: {usage['last_stage']}\n"
                      f"Process exit code: {child.returncode}\nError: {result}")
    save(job['id'], status, usage)
    result = (result[-1500:] + '\n' + summary(usage)).strip()
    http.post(base + '/finish', json={'status':status, 'result':result}).raise_for_status()


def main():
    tokenizer = load_tokenizer()
    with httpx.Client(headers={'Authorization':'Bearer ' + os.environ['WC_HARNESS_WORKER_KEY']},
                      timeout=4, follow_redirects=False) as http:
        while True:
            if not saved_api_key():
                time.sleep(5)
                continue
            try:
                response = http.post(ROOT + '/claim')
                response.raise_for_status()
                if response.status_code != 204:
                    run_job(http, response.json(), tokenizer)
            except httpx.HTTPError as exc:
                print('Queue request failed:', type(exc).__name__, flush=True)
            time.sleep(3)


if __name__ == '__main__':
    main()
