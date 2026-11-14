"""Contact v3 transport/cancellation and automatic cross-flash regressions."""
import asyncio
import hmac
from pathlib import Path
import struct
import subprocess
import sys
from types import SimpleNamespace

import pytest

from openpilot.selfdrive.carrot.bluetooth import b1_monitor as b1
from tools.carrot_b1 import auto_update as auto


def source(now, ident='one', direction='left', held=True):
  event = {'id': ident, 'time': now, 'direction': direction, 'device': 'remote'}
  return {'stamp': now, 'ok': True, 'events': [] if held else [event],
          'hold': event if held else None, 'devices': ['remote']}


def test_relay_hold_is_cancelled_immediately_and_never_repeated():
  i = b1.RelayIntent()
  now = i.started + .1
  s = source(now)
  assert i.choose(s, 'ready', 0, now)[:2] == (1, 'one')
  i.inflight = 7, 'one', now
  assert i.choose(s, 'waiting', 6, now+.02)[0] == 0
  assert i.choose(s, 'waiting', 7, now+.03)[0] == 4
  # No fingerprint-specific flag is needed for contact-mode holds.
  s['hold'] = None
  assert i.choose(s, 'waiting', 7, now+.04)[0] == 3
  s['hold'] = source(now)['hold']
  assert i.choose(s, 'ready', 0, now+.05)[0] == 0


@pytest.mark.parametrize('change', ['device', 'direction', 'id', 'stale', 'invalid', 'fault'])
def test_relay_revocations(change):
  i = b1.RelayIntent(); now = i.started + .1; s = source(now)
  i.choose(s, 'ready', 0, now); i.inflight = 9, 'one', now
  state = 'waiting'; stamp = now+.05
  if change == 'device': s['devices'] = []
  if change == 'direction': s['hold']['direction'] = 'right'
  if change == 'id': s['hold']['id'] = 'new'
  if change == 'stale': stamp = now+.21
  if change == 'invalid': s['ok'] = False
  if change == 'fault': state = 'error'
  assert i.choose(s, state, 9, stamp)[0] == 3
  assert i.inflight is None


def test_opposite_request_breaks_before_new_start():
  i = b1.RelayIntent(); now = i.started + .1
  s = source(now, held=False)
  assert i.choose(s, 'ready', 0, now)[0] == 1
  i.inflight = 1, 'one', now
  other = source(now+.05, 'two', 'right', held=False)
  assert i.choose(other, 'waiting', 1, now+.05)[0] == 3
  assert i.choose(other, 'waiting', 0, now+.10)[0] == 0
  assert i.choose(other, 'ready', 0, now+.15)[:2] == (2, 'two')


def test_no_implicit_restart_after_output_timeout():
  i = b1.RelayIntent(); now = i.started + .1; s = source(now)
  i.choose(s, 'ready', 0, now); i.inflight = 9, 'one', now
  assert i.choose(s, 'error', 0, now+.05)[0] == 3
  s['stamp'] = now+.1
  assert i.choose(s, 'ready', 0, now+.1)[0] == 0


@pytest.fixture(scope='module')
def controller(tmp_path_factory):
  folder = tmp_path_factory.mktemp('relay-controller')
  exe = folder/'controller'
  subprocess.run(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                  str(Path(__file__).with_name('test_relay.cpp')), '-o', str(exe)], check=True)
  return exe


@pytest.mark.parametrize('direction,expected', [('left', 1), ('right', 2)])
def test_real_monitor_to_production_controller(monkeypatch, tmp_path, controller, direction, expected):
  # No BlueZ calls or sockets: a subprocess runs the firmware's actual controller.
  from tools.jetlink import blink_protocol
  clock = SimpleNamespace(now=10.)
  monkeypatch.setattr(b1.time, 'monotonic', lambda: clock.now)
  monkeypatch.setattr(b1, 'BADGE', tmp_path/'badge')
  params = SimpleNamespace(get_bool=lambda name: name == 'IsOnroad')
  monkeypatch.setitem(sys.modules, 'openpilot.common.params', SimpleNamespace(Params=lambda: params))
  key = bytes(range(32)); writes = []; feedback = []
  data = source(clock.now+.1, direction=direction)
  worker = SimpleNamespace(process=SimpleNamespace(poll=lambda: None), send=feedback.append, close=lambda: None)
  def latest():
    data['stamp'] = clock.now
    return data
  worker.latest = latest
  monkeypatch.setattr(blink_protocol, 'Process', lambda *_: worker)
  child = subprocess.Popen([str(controller), 'wire'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
  status = [0, 0, 0, 0, 'idle']
  def step(packet=None):
    nonlocal status
    now = round((clock.now-10.)*1000)+1000
    line = f'T {now}' if packet is None else 'R '+str(now)+' '+' '.join(map(str, struct.unpack('<IIHBB', packet[:12])))
    child.stdin.write(line+'\n'); child.stdin.flush()
    fields = child.stdout.readline().split()
    status = [*map(int, fields[:4]), fields[4]]
  async def board(path, interface, method, sig, body, reply_timeout):
    if path == 'meta':
      step()
      mask, ack, seq, fault, _ = status
      return (struct.pack('<IIHBBBH', 42, round((clock.now-10)*1000)+1000,
                          ack, 5 if fault else 3 if mask else 1, mask, 3, seq),)
    packet = body[0]
    assert hmac.compare_digest(packet[12:], hmac.digest(key, packet[:12], 'sha256')[:8])
    writes.append(packet[10]); step(packet)
  async def run():
    m = b1.Monitor(); m.attrs = {b1.META: 'meta', b1.CONTROL: 'control'}; m.params = params; m.client.call = board
    await m.exchange(key)
    assert writes == [3] and m.protocol_version == 3
    clock.now += .1; m.next_start = 0
    await m.exchange(key)
    assert writes[-1] == expected and status[0] == expected
    clock.now += .05
    await m.exchange(key)
    assert writes[-1] == expected+3 and status[0] == expected
    assert feedback[-1]['accepted_id'] == 'one'
    assert feedback[-1]['lamps'] is None and feedback[-1]['outputs'] == expected
    badge = b1.read_json(b1.BADGE)
    assert badge['lamps'] is None and badge['mode'] == 'relay'
    # A fresh source without the old hold sends STOP in the very next exchange.
    data['hold'] = None; clock.now += .05
    await m.exchange(key)
    assert writes[-1] == 3 and status[0] == 0
  try:
    asyncio.run(run())
  finally:
    child.stdin.close(); child.wait(timeout=2); child.stdout.close()


def test_relay_cannot_receive_automatic_can_image(monkeypatch):
  monkeypatch.setitem(sys.modules, 'tools.carrot_b1.comma_update', SimpleNamespace(Client=None))
  m = SimpleNamespace(protocol_version=3)
  assert asyncio.run(auto.check(m, b'never sent', (1, 'a'*64), 'mac', 42)) == 'relay firmware: manual bench update only'


def test_relay_badge_never_says_can(tmp_path):
  from openpilot.selfdrive.ui.b1_badge import status
  enrollment = tmp_path/'enrolled'; enrollment.touch(); path = tmp_path/'badge'
  for state in ('ready', 'waiting', 'error'):
    b1.atomic_json(path, {'time':10, 'state':state, 'mode':'relay', 'lamps':None, 'outputs':0})
    assert status(10.1, enrollment, path) == 'relay_'+state
  b1.atomic_json(path, {'time':10, 'state':'waiting', 'mode':'relay', 'lamps':None, 'outputs':1})
  assert status(10.1, enrollment, path) == 'relay_on'


def test_actual_source_loop_recognizes_relay_without_can_relight(monkeypatch):
  import json
  from contextlib import nullcontext
  import blink_source as source_module
  from test_blinker import Vehicle
  from openpilot.selfdrive.carrot.bluetooth import model
  clock, sent, reads = [10.], [], [0]
  sm = Vehicle()
  def update(_):
    clock[0] += .001
    sm.recv_time = dict.fromkeys(sm.services, clock[0])
  sm.update = update
  monkeypatch.setitem(sys.modules, 'openpilot.common.params', SimpleNamespace(Params=lambda: SimpleNamespace(
    get=lambda _: b'cp', get_int=lambda _: 0)))
  monkeypatch.setitem(sys.modules, 'openpilot.cereal', SimpleNamespace(
    messaging=SimpleNamespace(SubMaster=lambda _: sm),
    car=SimpleNamespace(CarParams=SimpleNamespace(from_bytes=lambda _: nullcontext(
      SimpleNamespace(carFingerprint='HYUNDAI_IONIQ_5_PE'))))))
  peer = {'stamp':10., 'state':'ready', 'relay':True, 'lamps':None, 'outputs':0, 'accepted_id':None}
  def receive(_):
    reads[0] += 1
    return json.dumps(peer).encode() if reads[0] == 1 else b''
  sock = SimpleNamespace(setblocking=lambda _: None, recv=receive, send=lambda raw: sent.append(json.loads(raw)))
  monkeypatch.setattr(source_module.socket, 'socket', lambda **_: sock)
  monkeypatch.setattr(source_module.select, 'select', lambda *_: ([sock] if reads[0] == 0 or sent else [], [], []))
  monkeypatch.setattr(source_module.time, 'monotonic', lambda: clock[0])
  monkeypatch.setattr(source_module.time, 'sleep', lambda _: None)
  monkeypatch.setattr(model, 'read_json', lambda *_: {})
  monkeypatch.setattr(model, 'config', dict)
  monkeypatch.setattr(model, 'atomic_json', lambda *_: None)
  def forbidden_relight(*_, **__):
    raise AssertionError('relay mode must not use CAN one-touch relight')
  monkeypatch.setattr(source_module.Policy, 'relight', forbidden_relight)
  source_module.main(0, ble=True)
  assert len(sent) == 1 and sent[0]['ok'] is True and sent[0]['b1_hold'] is True
