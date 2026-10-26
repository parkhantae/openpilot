"""Read-only Porter log evidence summary. Never sends CAN or infers engagement.

The 0x371 set-speed field is a candidate: a confirmed 50 -> 0 cancellation
observation does not establish MAIN/SET/RES behavior across speeds.
"""
import argparse
from collections import Counter
import json
from pathlib import Path


def decode_candidate(address, payload):
    """Extract existing hyundai_kia_generic.dbc fields from RX bus 0 only.

    The caller selects the bus. No active/available state is synthesized.
    Reject short/long packets instead of decoding padded or truncated bytes.
    """
    if address == 0x371 and len(payload) == 8:
        bits = int.from_bytes(payload, 'little')
        return {'set_speed_candidate': (bits >> 23) & 0xff,
                'limit_status_candidate': (bits >> 13) & 1,
                'brake_pedal_candidate': bits & 0xff}
    if address == 0x394 and len(payload) == 8:
        bits = int.from_bytes(payload, 'little')
        return {'driver_override': (bits >> 45) & 3,
                'driver_braking': (bits >> 55) & 1,
                'parking_brake': (bits >> 53) & 1}
    if address == 0x4f1 and len(payload) == 4:
        return {'cruise_button': payload[0] & 7,
                'main_button': (payload[0] >> 3) & 1}
    return {}


def summarize(path, schema_path, car_schema_dir):
    # Keep schema and decompressor dependencies out of the pure decoder tests.
    import capnp
    import zstandard
    schema_path = Path(schema_path).resolve()
    schema = capnp.load(str(schema_path), imports=[str(schema_path.parent), str(Path(car_schema_dir).resolve())])
    with Path(path).open('rb') as source:
        with zstandard.ZstdDecompressor().stream_reader(source) as reader:
            data = reader.read()
    counts = Counter()
    values = {}
    fingerprints = Counter()
    controls = Counter()
    state_summary = Counter()
    tx = Counter()
    first_state_time = last_state_time = None
    for event in schema.Event.read_multiple_bytes(data, traversal_limit_in_words=2**27):
        kind = event.which()
        counts[kind] += 1
        if kind == 'carParams':
            fingerprints[event.carParams.carFingerprint] += 1
        elif kind == 'carState':
            first_state_time = event.logMonoTime if first_state_time is None else first_state_time
            last_state_time = event.logMonoTime
            state = event.carState
            state_summary['brake_pressed_true'] += int(state.brakePressed)
            state_summary['cruise_enabled_true'] += int(state.cruiseState.enabled)
            state_summary['cruise_speed_nonzero'] += int(state.cruiseState.speed != 0)
        elif kind == 'carControl':
            controls['enabled_true'] += int(event.carControl.enabled)
            controls['long_active_true'] += int(event.carControl.longActive)
        elif kind == 'sendcan':
            for msg in event.sendcan:
                tx[f'{msg.src}:0x{msg.address:x}'] += 1
        elif kind == 'can':
            for msg in event.can:
                if msg.src != 0:
                    continue  # forwarded/returned frames are not independent OEM RX
                for key, value in decode_candidate(msg.address, msg.dat).items():
                    values.setdefault(key, Counter())[value] += 1
    duration = None if first_state_time is None else (last_state_time - first_state_time) / 1e9
    return {'car_fingerprints': dict(fingerprints), 'car_state_duration_seconds': duration,
            'message_counts': dict(counts), 'car_state_summary': dict(state_summary),
            'car_control_summary': dict(controls), 'sendcan_counts': dict(tx),
            'bus0_candidate_values': {k: dict(v) for k, v in values.items()},
            'limitations': 'Read-only evidence; candidate fields are not an engagement decoder or vehicle validation.'}


def main():
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('rlog', type=Path)
    parser.add_argument('--schema', type=Path, default=root / 'openpilot/cereal/log.capnp')
    parser.add_argument('--car-schema-dir', type=Path, default=root / 'opendbc_repo/opendbc/car')
    args = parser.parse_args()
    print(json.dumps(summarize(args.rlog, args.schema, args.car_schema_dir), indent=2))


if __name__ == '__main__':
    main()
