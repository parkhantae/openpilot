"""Parked relay bench tests; BOTH vehicle contact channels must be disconnected."""
import argparse
import asyncio
from contextlib import suppress
import struct
import time

META = 'db340a92-804c-4ead-af37-8a0e6af754a1'
CONTROL = 'db340a93-804c-4ead-af37-8a0e6af754a1'


async def exercise(client, key, check, mode='stop', direction='left'):
  from openpilot.selfdrive.carrot.bluetooth.b1_monitor import command
  session = None
  seq = 0
  disconnected = False

  async def report():
    check()
    raw = await asyncio.wait_for(client.read_gatt_char(META), .3)
    r = struct.unpack('<IIHBBBH', bytes(raw))
    if not r[0] or r[5] != 3 or r[4] not in (0, 1, 2):
      raise RuntimeError('Invalid/non-relay board report')
    if session is not None and r[0] != session:
      raise RuntimeError('Board session changed; no restart permitted')
    check()
    return r

  async def send(op):
    nonlocal seq
    r = await report()
    seq = (seq + 1) % 65536 or 1
    check()
    await asyncio.wait_for(client.write_gatt_char(CONTROL, command(key, session, r[1], seq, op, .35), response=True), .3)
    return seq

  try:
    initial = await report()
    session, seq = initial[0], initial[6]
    if initial[3] != 1 or initial[4]:
      raise RuntimeError('Board must be READY with both outputs OFF')
    await send(3)
    await asyncio.sleep(.12)
    wanted = 1 if direction == 'left' else 2
    started = time.monotonic()
    active_seq = await send(wanted)
    await asyncio.sleep(.04)
    end = started + (12.5 if mode == 'limit' else 1.)
    while time.monotonic() < end:
      r = await report()
      elapsed = time.monotonic() - started
      if mode == 'limit' and r[3] == 5 and r[4] == 0:
        if elapsed < 9.5:
          raise RuntimeError('Output faulted before the expected ON limit')
        await send(wanted + 3)  # A hold must not restart a timed-out output.
        await asyncio.sleep(.08)
        if (await report())[4]:
          raise RuntimeError('Timed-out output restarted')
        return {'test':'limit', 'reported_off_after_s':round(elapsed,3), 'outputs':0}
      if r[4] != wanted or r[2] != active_seq:
        raise RuntimeError(f'Expected only channel {wanted}, exact ACK {active_seq}; got mask={r[4]}, ack={r[2]}, state={r[3]}')
      await send(wanted + 3)
      await asyncio.sleep(.07)
    if mode == 'limit':
      raise RuntimeError('No maximum-time cutoff observed; stopping')
    if mode == 'disconnect':
      # BlueZ may acknowledge after link teardown; output leases still expire at 350ms.
      await asyncio.wait_for(client.disconnect(), 5.)
      disconnected = True
      await asyncio.sleep(1.)
      return {'test':'disconnect', 'disconnect_confirmed':True, 'physical_OFF_requires_user_observation':True}
    if mode == 'stop':
      stop_seq = await send(3)
      await asyncio.sleep(.08)
      r = await report()
      if r[4] or r[6] != stop_seq:
        raise RuntimeError('STOP acknowledgement/OFF missing')
      return {'test':'stop', 'stop_seq':stop_seq, 'outputs':0}
    # Read-only polling after the last hold; do not renew its lease.
    stopped = time.monotonic()
    for _ in range(12):
      await asyncio.sleep(.05)
      r = await report()
      if not r[4]:
        return {'test':'lease', 'reported_off_after_s':round(time.monotonic()-stopped,3), 'outputs':0}
    raise RuntimeError('Lease OFF not observed; stopping')
  finally:
    if session is not None and not disconnected:
      # Cleanup must still attempt STOP if the vehicle guard fails.
      with suppress(Exception):
        raw = await asyncio.wait_for(client.read_gatt_char(META), .3)
        r = struct.unpack('<IIHBBBH', bytes(raw))
        if r[0] == session and r[5] == 3:
          cleanup_seq = (r[6]+1)%65536 or 1
          await asyncio.wait_for(client.write_gatt_char(CONTROL, command(key, session, r[1], cleanup_seq, 3, .35), response=True), .3)


async def run(args):
  import fcntl
  import json
  from pathlib import Path
  from tools.carrot_b1.comma_update import ParkGuard, Client
  from openpilot.selfdrive.carrot.bluetooth.b1_monitor import ENROLLMENT, GATT, SERVICE, OTA_LOCK
  from openpilot.selfdrive.carrot.bluetooth.bluez import Bluez, DEVICE, properties
  from openpilot.selfdrive.carrot.bluetooth.model import address, read_json
  if not Path('/TICI').is_file():
    raise RuntimeError('Run on comma through SSH')
  guard = ParkGuard()
  for _ in range(20):
    guard.sm.update(100)
    await asyncio.sleep(.1)
  guard.check()
  if guard.params.get_int('AutoBlinkerControl') != 0 or guard.params.get_bool('CanfdBlinkerControl'):
    raise RuntimeError('Keep AutoBlinkerControl=0 and CanfdBlinkerControl=False')
  registration = read_json(ENROLLMENT, {})
  mac, key = address(registration.get('address')), bytes.fromhex(registration['key'])
  if len(key) != 32:
    raise RuntimeError('Invalid registration key')
  bus = Bluez()
  try:
    with OTA_LOCK.open('ab') as lock:
      fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
      # Pause ordinary command writes and expire the old control lease.
      await asyncio.sleep(.8)
      guard.check()
      objects = await bus.objects()
      attrs = {}
      for path, interfaces in objects.items():
        char = properties(interfaces.get(GATT, {}))
        service = properties(objects.get(char.get('Service'), {}).get('org.bluez.GattService1', {}))
        device = properties(objects.get(service.get('Device'), {}).get(DEVICE, {}))
        if service.get('UUID') == SERVICE and device.get('Address') == mac and device.get('Connected'):
          attrs[char['UUID']] = path
      if not {META, CONTROL}.issubset(attrs):
        raise RuntimeError('Enrolled B1 is not connected/resolved')
      client = Client(bus, attrs)
      async def disconnect():
        await bus.device_action(mac, 'disconnect')
      client.disconnect = disconnect
      print(f'Bench {args.test}, {args.direction}: ONE start only; no automatic retry.', flush=True)
      result = await exercise(client, key, guard.check, args.test, args.direction)
      print(json.dumps(result), flush=True)
      print('Board reports are logical outputs; confirm physical LEDs/contacts separately.', flush=True)
  finally:
    await bus.close()


def main():
  p = argparse.ArgumentParser(description=__doc__)
  p.add_argument('--vehicle-contacts-disconnected', action='store_true')
  p.add_argument('--test', choices=('stop','lease','limit','disconnect'), default='stop')
  p.add_argument('--direction', choices=('left','right'), default='left')
  args = p.parse_args()
  if not args.vehicle_contacts_disconnected:
    p.error('Disconnect BOTH vehicle contact channels first')
  asyncio.run(run(args))


if __name__ == '__main__':
  main()
