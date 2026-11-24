"""S2 reflects a fresh HID reader connection, never just a saved pairing."""
import json

import pytest

from openpilot.selfdrive.ui import s2_status


@pytest.mark.parametrize('record,expected', [
  ({'time': 10., 'grabbed': ['AA:BB:CC:DD:EE:FF']}, True),
  ({'time': 10., 'grabbed': []}, False),
  ({'time': 10., 'grabbed': ['AA:BB:CC:DD:EE:FF'], 'stopped': True}, False),
  ({'time': 8., 'grabbed': ['AA:BB:CC:DD:EE:FF']}, False),
  ({'time': 10.1, 'grabbed': ['AA:BB:CC:DD:EE:FF']}, False),
  ({'time': 10., 'grabbed': 'AA:BB:CC:DD:EE:FF'}, False),
  ({'time': 10., 'grabbed': [None, '']}, False),
  ({'time': '10', 'grabbed': ['AA:BB:CC:DD:EE:FF']}, False),
  ({'grabbed': ['AA:BB:CC:DD:EE:FF']}, False),
  ([], False),
])
def test_reader_connection_requires_fresh_live_device(tmp_path, record, expected):
  path = tmp_path / 'status.json'
  path.write_text(json.dumps(record))
  assert s2_status.read_connected(10., path) is expected


def test_missing_or_partial_snapshot_hides_label(tmp_path):
  path = tmp_path / 'status.json'
  assert not s2_status.read_connected(10., path)
  path.write_text('{"time":10,"grabbed":[')
  assert not s2_status.read_connected(10., path)


def test_normal_reader_event_history_does_not_truncate_status(tmp_path):
  path = tmp_path / 'status.json'
  path.write_text(json.dumps({'time': 10., 'grabbed': ['AA:BB:CC:DD:EE:FF'],
                              'recent_events': [{'button': 'x' * 256} for _ in range(128)]}))
  assert path.stat().st_size > 4096
  assert s2_status.read_connected(10., path)


def test_cache_refreshes_connection_and_disconnect_without_per_frame_reads(monkeypatch):
  clock, reads, live = [10.], [], [True]
  monkeypatch.setattr(s2_status.time, 'monotonic', lambda: clock[0])
  monkeypatch.setattr(s2_status, '_next', 0.)
  monkeypatch.setattr(s2_status, '_connected', False)

  def read(now):
    reads.append(now)
    return live[0]

  monkeypatch.setattr(s2_status, 'read_connected', read)
  assert s2_status.connected()
  live[0] = False
  clock[0] = 10.1
  assert s2_status.connected()
  assert reads == [10.]
  clock[0] = 10.36
  assert not s2_status.connected()
  assert reads == [10., 10.36]
  clock[0] = 1.
  assert not s2_status.connected()
  assert reads[-1] == 1.
