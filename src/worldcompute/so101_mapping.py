"""Convert between calibrated World Compute and SO101 model coordinates."""
import math

JOINTS = ('shoulder_pan', 'shoulder_lift', 'elbow_flex', 'wrist_flex', 'wrist_roll')


def model_state(joints, mapping):
    result = []
    for name in JOINTS:
        value = joints[name]
        transform = mapping['joints'][name]
        sign, offset = transform['sign'], transform['offset_degrees']
        if (type(value) not in (int, float) or not math.isfinite(value)
                or type(sign) not in (int, float) or sign not in (-1, 1)
                or type(offset) not in (int, float) or not math.isfinite(offset)):
            raise ValueError(f'Invalid mapping or measured value for {name}')
        result.append(math.degrees(value) * sign + offset)
    closed, opened = mapping['gripper_closed_rad'], mapping['gripper_open_rad']
    gripper = joints['gripper']
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in (closed, opened, gripper)) or closed == opened:
        raise ValueError('Gripper requires distinct calibrated endpoints and finite feedback')
    percent = (gripper - closed) / (opened - closed) * 100
    if not 0 <= percent <= 100:
        raise ValueError('Measured gripper is outside its declared calibrated range')
    result.append(percent)
    return result


def arm_target(name, degrees, mapping):
    transform = mapping['joints'][name]
    radians = math.radians((float(degrees) - transform['offset_degrees']) / transform['sign'])
    if not math.isfinite(radians):
        raise ValueError(f'Expected finite target for {name}')
    return radians


def wc_targets(rows, mapping):
    converted = []
    for row in rows:
        if len(row) != 6 or any(not math.isfinite(float(v)) for v in row):
            raise ValueError('Expected six finite absolute action values')
        if not 0 <= row[5] <= 100:
            raise ValueError('Predicted gripper outside 0–100')
        target = {}
        for index, name in enumerate(JOINTS):
            target[name] = arm_target(name, row[index], mapping)
        target['gripper'] = mapping['gripper_closed_rad'] + float(row[5]) / 100 * (
            mapping['gripper_open_rad'] - mapping['gripper_closed_rad'])
        converted.append(target)
    return converted
