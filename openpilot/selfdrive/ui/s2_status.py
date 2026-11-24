"""Cached, display-only Bluetooth HID connection state from the input reader."""
import json
from pathlib import Path
import time

STATUS = Path('/dev/shm/carrot-bluetooth/status.json')


def read_connected(now, path=STATUS):
  try:
    with path.open('rb') as stream:
      # The reader also includes up to 128 recent events in this snapshot.
      record = json.loads(stream.read(128 * 1024))
    return bool(isinstance(record, dict) and not record.get('stopped') and
                0 <= now - record['time'] < 2 and isinstance(record.get('grabbed'), list) and
                any(isinstance(device, str) and device for device in record['grabbed']))
  except (OSError, KeyError, ValueError, TypeError):
    return False


_next = 0.
_connected = False


def connected():
  global _next, _connected
  now = time.monotonic()
  if now >= _next or now < _next - .35:
    _connected = read_connected(now)
    _next = now + .35
  return _connected
