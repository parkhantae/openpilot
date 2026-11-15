"""One stationary indicator tap through the existing guarded policy. No raw CAN."""
import argparse
import json
from pathlib import Path
import time

STATUS = Path('/dev/shm/carrot-b1-link.json')


def request_once(guard, runtime, atomic_json, direction):
  guard.check()
  if guard.params.get_int('AutoBlinkerControl') != 0 or guard.params.get_bool('CanfdBlinkerControl'):
    raise RuntimeError('Require AutoBlinkerControl=0 and CanfdBlinkerControl=False; no setting was changed')
  last = None
  for _ in range(60):
    guard.check()
    cs = guard.sm['carState']
    if cs.leftBlinker or cs.rightBlinker:
      raise RuntimeError('Wait until existing vehicle signals finish; no request sent')
    last = json.loads(STATUS.read_text())
    age = time.monotonic() - last['time']
    if (0 <= age < .5 and last.get('mode') == 'relay' and last.get('state') == 'ready'
        and last.get('source_ready') is True and last.get('outputs') == 0):
      ident = 'park-test:' + str(time.monotonic_ns())
      atomic_json(runtime/'b1-park-test.json', {'id':ident, 'time':time.monotonic(), 'direction':direction})
      return ident
    time.sleep(.05)
  raise RuntimeError(f'No request sent: stale/unready B1; age={age:.3f}s, status={last}')


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--direction', choices=('left','right'), required=True)
  args = parser.parse_args()
  from tools.carrot_b1.comma_update import ParkGuard
  from openpilot.selfdrive.carrot.bluetooth.model import RUNTIME, atomic_json
  guard = ParkGuard()
  for _ in range(20):
    guard.sm.update(100)
    time.sleep(.1)
  ident = request_once(guard, RUNTIME, atomic_json, args.direction)
  print(f'ONE {args.direction} pulse requested: {ident}. Vehicle one-touch flashes may continue after relay OFF.', flush=True)
  previous = None
  try:
    for _ in range(160):
      guard.check()
      cs = guard.sm['carState']
      lamps = (cs.leftBlinker, cs.rightBlinker)
      if lamps != previous:
        print('Vehicle left/right:', lamps, flush=True)
        previous = lamps
      time.sleep(.05)
    record = json.loads(STATUS.read_text())
    print('B1 final:', json.dumps(record), flush=True)
    print('B1 report age seconds:', round(time.monotonic()-record['time'],3), flush=True)
  finally:
    path = RUNTIME/'b1-park-test.json'
    try:
      if json.loads(path.read_text()).get('id') == ident:
        path.unlink()
    except (OSError, ValueError):
      pass


if __name__ == '__main__':
  main()
