"""Read-only comparison of OEM buttons, injected buttons and TX echoes.

Counter overlap is an observation, not proof that the ECU rejected a packet.
No CAN transmission, firmware changes or raw identifying log content is emitted.
"""
import argparse
from bisect import bisect_left, bisect_right
from collections import Counter
from dataclasses import dataclass
import json


@dataclass(frozen=True)
class ButtonFrame:
  time: float
  bus: int
  payload: bytes

  @property
  def button(self):
    return self.payload[0] & 7

  @property
  def counter(self):
    return self.payload[3] >> 4


def press_groups(frames):
  groups = []
  current = None
  for frame in sorted(frames, key=lambda f: f.time):
    if current is not None and (frame.time - current['frames'][-1].time > .1 or
                                frame.button not in (0, current['button'])):
      groups.append(current)
      current = None
    if frame.button:
      if current is None:
        current = {'button': frame.button, 'frames': [], 'release': None}
      current['frames'].append(frame)
    elif current is not None:
      current['release'] = frame.time
      groups.append(current)
      current = None
  if current is not None:
    groups.append(current)
  return groups


def analyze(oem, injected, echoes, speeds, origin=0.0):
  oem = sorted(oem, key=lambda f: f.time)
  injected = sorted(injected, key=lambda f: f.time)
  speeds = sorted(speeds)
  speed_times = [t for t, _ in speeds]
  oem_times = [f.time for f in oem]

  def describe(group):
    frames = group['frames']
    release = group['release']
    return {'start_seconds': round(frames[0].time - origin, 6), 'button': group['button'],
            'press_frames': len(frames),
            'press_to_release_ms': round((release - frames[0].time) * 1000, 3) if release is not None else None,
            'counter_steps': [(b.counter - a.counter) % 16 for a, b in zip(frames, frames[1:], strict=False)]}

  physical = [describe(g) for g in press_groups(oem)]
  groups = press_groups(injected)
  trials = []
  for i, group in enumerate(groups):
    item = describe(group)
    start = group['frames'][0].time
    end = min(start + .5, groups[i + 1]['frames'][0].time) if i + 1 < len(groups) else start + .5
    index = bisect_right(speed_times, start) - 1
    baseline = speeds[index][1] if index >= 0 else None
    changes = [value for _, value in speeds[bisect_right(speed_times, start):bisect_right(speed_times, end)]]
    nearby = oem[bisect_left(oem_times, start):bisect_right(oem_times, end)]
    if any(f.button for f in nearby):
      outcome = 'physical_button_overlap'
    elif baseline is None or not changes:
      outcome = 'insufficient_speed_data'
    elif baseline == 0 and any(v > 0 for v in changes):
      outcome = 'setting_appeared'
    elif any(v == 0 for v in changes):
      outcome = 'cruise_off'
    else:
      delta = [value - baseline for value in changes]
      direction = 1 if group['button'] == 1 else -1 if group['button'] == 2 else 0
      outcome = ('opposite_setting_change' if direction and any(d * direction < 0 for d in delta) else
                 'directional_setting_change' if direction and any(d * direction > 0 for d in delta) else
                 'no_setting_change')
    overlaps = 0
    for frame in group['frames']:
      window = oem[bisect_left(oem_times, frame.time - .04):bisect_right(oem_times, frame.time + .04)]
      overlaps += any(f.bus == frame.bus and f.counter == frame.counter and f.button != frame.button for f in window)
    item.update(speed_before_kph=baseline, outcome=outcome, same_counter_different_button_frames=overlaps)
    trials.append(item)

  intended = Counter((f.bus, f.payload) for f in injected)
  confirmed = Counter((f.bus, f.payload) for f in echoes)
  return {'oem_presses': physical, 'injected_requests': trials,
          'outcomes': dict(Counter(t['outcome'] for t in trials)),
          'injected_frames': len(injected), 'tx_echo_frames': len(echoes),
          'unmatched_intended_frames': sum((intended - confirmed).values()),
          'unmatched_echo_frames': sum((confirmed - intended).values()),
          'limitations': ['TX echo confirms transmission, not ECU acceptance.',
                          'Counter overlap alone is not a rejection cause.',
                          'Setting changes do not prove physical acceleration or braking.',
                          'Segment boundaries can omit presses, releases or feedback.']}


def analyze_logs(paths):
  # Use the full openpilot schema, not the reduced opendbc car-only reader.
  from openpilot.tools.lib.logreader import LogReader

  oem, injected, echoes, speeds = [], [], [], []
  origin = None
  for path in paths:
    for event in LogReader(path):
      kind, time = event.which(), event.logMonoTime / 1e9
      if kind == 'carState':
        origin = time if origin is None else min(origin, time)
      if kind not in ('can', 'sendcan'):
        continue
      for message in getattr(event, kind):
        payload = bytes(message.dat)
        if kind == 'can' and message.src == 0 and message.address == 0x371 and len(payload) == 8:
          speeds.append((time, int.from_bytes(payload, 'little') >> 23 & 255))
        if message.address != 0x4f1 or len(payload) != 4:
          continue
        if kind == 'sendcan' and message.src == 0:
          injected.append(ButtonFrame(time, 0, payload))
        elif kind == 'can' and message.src == 0:
          oem.append(ButtonFrame(time, 0, payload))
        elif kind == 'can' and message.src == 128:
          echoes.append(ButtonFrame(time, 0, payload))
  return analyze(oem, injected, echoes, speeds, origin or 0.0)


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('rlogs', nargs='+', help='Consecutive local rlogs in the same boot/session')
  args = parser.parse_args()
  print(json.dumps(analyze_logs(args.rlogs), indent=2))


if __name__ == '__main__':
  main()
