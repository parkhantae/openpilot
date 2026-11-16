"""Reconnect an enrolled board without relying on a transient scan RSSI."""
import asyncio
from types import SimpleNamespace

import pytest

from openpilot.selfdrive.carrot.bluetooth import b1_monitor as b1

MAC = '00:00:00:00:00:01'


def device(**changes):
  props = dict(Address=MAC, Name='Carrot-B1', UUIDs=[b1.SERVICE], Paired=True, Connected=False)
  props.update(changes)
  return {'/board': {b1.DEVICE: {k: ('v', v) for k, v in props.items()}}}


@pytest.mark.parametrize('rssi', [None, -45])
def test_bonded_board_reconnects_without_a_new_advertisement(rssi):
  async def run():
    m = b1.Monitor()
    calls = []
    async def objects():
      return device(**({} if rssi is None else {'RSSI': rssi}))
    async def action(mac, operation):
      calls.append((mac, operation))
    async def scan():
      calls.append('scan')
    m.client = SimpleNamespace(objects=objects, device_action=action, scan=scan)
    assert await m.discover(MAC) == 'connecting'
    assert calls == [(MAC, 'connect')]
    assert m.owned == MAC and m.attrs is None and m.worker is None
  asyncio.run(run())


@pytest.mark.parametrize('changes', [{'Paired': False}, {'Name': 'Other'}, {'UUIDs': []}, {'Address': '00:00:00:00:00:02'}])
def test_no_blind_connect_to_unseen_or_unmatched_device(changes):
  async def run():
    m = b1.Monitor()
    calls = []
    async def objects():
      return device(**changes)
    async def action(*args):
      calls.append(args)
    async def scan():
      calls.append('scan')
    m.client = SimpleNamespace(objects=objects, device_action=action, scan=scan)
    assert await m.discover(MAC) == 'scanning'
    assert calls == ['scan'] and m.owned is None
  asyncio.run(run())


def test_disconnect_invalidates_ready_before_waiting_for_bluez(monkeypatch, tmp_path):
  monkeypatch.setattr(b1, 'BADGE', tmp_path/'badge')
  async def run():
    m = b1.Monitor()
    during_disconnect = []
    m.protocol_version = 3
    m.source = {'ok': True, 'stamp': b1.time.monotonic()}
    m.session = 7
    m.owned, m.attrs = MAC, {'meta': 'old'}
    m.intent = b1.RelayIntent()
    m.intent.inflight = (9, 'old-turn', b1.time.monotonic())
    m.sent_sequences.append(9)
    m.proven_at = b1.time.monotonic()
    m.publish_badge('ready', b1.time.monotonic(), None, 'old-turn', 0)
    async def action(mac, operation):
      value = b1.read_json(b1.BADGE)
      during_disconnect.append((mac, operation, value))
    async def close():
      pass
    m.client = SimpleNamespace(device_action=action, close=close)
    await m.release()
    mac, operation, value = during_disconnect[0]
    assert (mac, operation) == (MAC, 'disconnect')
    assert value['state'] == 'missing' and value['source_ready'] is False
    assert value['outputs'] is None and value['accepted_id'] is None
    assert m.source is None and m.worker is None and m.session is None
    assert m.intent.inflight is None and not m.sent_sequences and m.proven_at < 0
  asyncio.run(run())


def test_scanning_report_expires_previous_ready_and_logs_no_secrets(monkeypatch, tmp_path):
  monkeypatch.setattr(b1, 'BADGE', tmp_path/'badge')
  m = b1.Monitor()
  events = []
  m.report = lambda event, **fields: events.append((event, fields))
  m.protocol_version = 3
  m.source = {'ok': True, 'stamp': b1.time.monotonic()}
  m.publish_badge('ready', b1.time.monotonic(), None, None, 0)
  m.unavailable('waiting to reconnect', RuntimeError('private transport data'))
  m.unavailable('waiting to reconnect', RuntimeError('private transport data'))
  value = b1.read_json(b1.BADGE)
  assert value['state'] == 'missing' and not value['source_ready'] and value['outputs'] is None
  assert events == [('b1LinkState', {'link_state': 'waiting to reconnect', 'error_type': 'RuntimeError'})]
