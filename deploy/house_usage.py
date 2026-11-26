"""Workstation measurements for house-funded Molmo runs."""
import json
import re
import sqlite3
from pathlib import Path

from tokenizers import Tokenizer

WORK = Path.home() / '.local/share/wc-harness'
# DreamScale model catalog, 2026-11-20. Estimate uses the observed ready-to-close interval.
HOURLY_USD = 5.0


def measure(stream, tokens, elapsed):
    stream.seek(0)
    events = []
    for line in stream:
        try:
            events.append(json.loads(line))
        except (ValueError, UnicodeDecodeError):
            continue  # The worker may have interrupted an event write.
    requests = [e for e in events if e['event'] == 'request']
    replies = [e for e in events if e['event'] == 'response']
    times = {e['event']: e['at'] for e in events}
    duration = None
    if 'session_closed' in times and 'session_ready' in times:
        duration = times['session_closed'] - times['session_ready']

    def total(field):
        if replies and all(e.get(field) is not None for e in replies):
            return sum(e[field] for e in replies)
        return None

    stages = {'session_ready': 'Model session ready', 'request': 'Observation prepared for inference',
              'response': 'Prediction received', 'session_closed': 'Model session closed'}
    last_stage = next((stages[e['event']] for e in reversed(events) if e['event'] in stages),
                      'Harness process started')
    return dict(last_stage=last_stage, model='molmoact2-so101', prompt_tokens=tokens,
                attempted_prompt_tokens=tokens * len(requests), predictions_attempted=len(requests),
                predictions_returned=len(replies), camera_inputs=sum(e['frames'] for e in requests),
                action_values=sum(e['action_values'] for e in replies), upload_bytes=total('upload_bytes'),
                prediction_ms=total('latency_ms'), server_inference_ms=total('inference_ms'),
                elapsed_s=elapsed, observed_session_s=duration, rate_snapshot_usd_hour=HOURLY_USD,
                estimated_session_usd=None if duration is None else duration * HOURLY_USD / 3600,
                provider_input_tokens=None, provider_output_tokens=None, billed_usd=None)


def subprocess_error(log):
    # Never publish arbitrary stderr: exceptions may carry URLs, tokens or prompt text.
    log.seek(0, 2)
    log.seek(max(0, log.tell() - 16384))
    lines = log.read().decode(errors='replace').splitlines()
    location = ''
    reason = 'No recognized exception in subprocess output'
    known = ('Pre-move check failed', 'Observation unavailable', 'Waypoint tracking incomplete',
             'Nonfinite Molmo waypoint', 'Unexpected Molmo action shape', 'Hold unconfirmed',
             'Expected one finite target per measured joint', 'Viewing connection disconnected',
             'Camera reception failed', 'Missing valid station clock sample')
    for line in lines:
        if line.startswith('Traceback ('):
            location = ''
        frame = re.fullmatch(r'  File "[^"]*/(task_rollout|molmo|session|observation|so101_mapping|client)\.py", line (\d{1,6}), in .+', line)
        if frame:
            location = f' ({frame[1]}.py line {frame[2]})'
        exception = re.fullmatch(r'(?:[\w.]+\.)?(RuntimeError|ValueError|ControlsError|TimeoutError|TrackingIncomplete|OutcomeUnknown|TypeError|KeyError|HTTPStatusError|ConnectionError|AttributeError|OSError)(?:: (.*))?', line)
        if exception:
            detail = next((label for label in known if (exception[2] or '').startswith(label)), '')
            if detail == 'Pre-move check failed':
                checks = [('controller timestamp outside', 'stale controller timestamp'),
                          ('missing or invalid controller timestamp', 'missing controller timestamp'),
                          ('drift exceeds', 'joint drift'), ('invalid controller reading', 'invalid joint reading')]
                matches = [label for marker, label in checks if marker in exception[2]]
                if matches:
                    detail += ' (' + ', '.join(matches) + ')'
            reason = exception[1] + (f': {detail}' if detail else '')
    return reason + location


def save(run_id, status, usage):
    with sqlite3.connect(WORK / 'usage.sqlite3') as db:
        db.execute('CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, saved_at TEXT, status TEXT, usage TEXT)')
        db.execute('INSERT OR REPLACE INTO runs VALUES (?, CURRENT_TIMESTAMP, ?, ?)',
                   (run_id, status, json.dumps(usage)))


def summary(u):
    text = (f"Prompt text: {u['prompt_tokens']} tokens per call, {u['attempted_prompt_tokens']} across attempts. "
            f"Predictions: {u['predictions_returned']}/{u['predictions_attempted']} returned. "
            f"Camera inputs: {u['camera_inputs']}. Action values: {u['action_values']}. "
            f"Run: {u['elapsed_s']:.2f}s.")
    if u['prediction_ms'] is not None:
        text += f" Prediction time: {u['prediction_ms']/1000:.2f}s total."
    if u['upload_bytes'] is not None:
        text += f" Uploaded: {u['upload_bytes']} bytes."
    if u['estimated_session_usd'] is not None:
        text += f" Session: {u['observed_session_s']:.2f}s, estimated ${u['estimated_session_usd']:.4f}."
    return text


def load_tokenizer():
    return Tokenizer.from_file(str(WORK / 'molmo-so101-tokenizer.json'))
