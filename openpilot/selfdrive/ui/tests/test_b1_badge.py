"""S3 connection labels follow current board reports, not enrollment alone."""
from functools import partial
import json

import pytest

from openpilot.selfdrive.ui import b1_badge


@pytest.fixture
def badge(tmp_path, monkeypatch):
  enrolled, path = tmp_path / 'enrolled', tmp_path / 'status.json'
  enrolled.touch()
  clock = [10.]
  monkeypatch.setattr(b1_badge.time, 'monotonic', lambda: clock[0])
  monkeypatch.setattr(b1_badge, '_next', 0.)
  monkeypatch.setattr(b1_badge, '_state', None)
  monkeypatch.setattr(b1_badge, 'status', partial(b1_badge.status, enrolled=enrolled, path=path))
  return enrolled, path, clock


@pytest.mark.parametrize('state,visible', [
  ('ready', True), ('waiting', True), ('sending', True),
  ('driver_override', True), ('error', True),
  ('offline', False), ('auth', False), ('missing', False),
  ('updating', False), ('unknown', False),
])
def test_connected_label_and_hidden_link_setup_states(badge, state, visible):
  _, path, _ = badge
  path.write_text(json.dumps({'time': 10., 'state': state}))
  assert b1_badge.presentation() == (('S3 연결됨', (255, 255, 255)) if visible else None)


@pytest.mark.parametrize('state,outputs', [('ready', 0), ('waiting', 0), ('waiting', 1), ('error', 0)])
def test_relay_reports_use_the_same_connection_label(badge, state, outputs):
  _, path, _ = badge
  path.write_text(json.dumps({'time': 10., 'state': state, 'mode': 'relay', 'outputs': outputs}))
  assert b1_badge.presentation() == ('S3 연결됨', (255, 255, 255))


def test_disconnect_refresh_and_silent_reader_expiry_hide_label(badge):
  _, path, clock = badge
  path.write_text(json.dumps({'time': 10., 'state': 'ready'}))
  assert b1_badge.presentation() is not None
  path.write_text(json.dumps({'time': 10.1, 'state': 'missing'}))
  clock[0] = 10.36
  assert b1_badge.presentation() is None
  path.write_text(json.dumps({'time': 10.4, 'state': 'ready'}))
  clock[0] = 10.72
  assert b1_badge.presentation() is not None
  clock[0] = 12.4
  assert b1_badge.presentation() is None


@pytest.mark.parametrize('failure', ['unregistered', 'missing', 'partial', 'future', 'stale'])
def test_missing_untrusted_or_stale_report_is_not_connected(badge, failure):
  enrolled, path, _ = badge
  path.write_text(json.dumps({'time': 10., 'state': 'ready'}))
  if failure == 'unregistered':
    enrolled.unlink()
  elif failure == 'missing':
    path.unlink()
  elif failure == 'partial':
    path.write_text('{"state":"ready",')
  else:
    path.write_text(json.dumps({'time': 11. if failure == 'future' else 8., 'state': 'ready'}))
  assert b1_badge.presentation() is None


def test_connection_report_can_include_full_last_command(badge):
  _, path, _ = badge
  path.write_text(json.dumps({'time': 10., 'state': 'ready', 'accepted_id': 'x' * 128,
                              'last_command': {'id': 'y' * 128, 'seq': 42, 'time': 10.}}))
  assert path.stat().st_size > 256
  assert b1_badge.presentation() == ('S3 연결됨', (255, 255, 255))
