from types import SimpleNamespace as NS

import pytest

from openpilot.cereal import car
from openpilot.selfdrive.car.porter_set_speed import PorterSetSpeedSync


def context():
  cp = NS(carFingerprint='HYUNDAI_PORTER_II_EV', pcmCruise=True, openpilotLongitudinalControl=False, safetyConfigs=[NS(safetyParam=15489)])
  cs = car.CarState(canValid=True, gearShifter='drive', vEgoCluster=50.37 / 3.6, cruiseState={'available': True, 'enabled': False, 'speed': 0.0})
  return NS(cp=cp, cs=cs, cc=car.CarControl(cruiseControl={'resume': True}), sync=PorterSetSpeedSync())


def tick(s, t, **kw):
  return s.sync.update(t, s.cp, s.cs, s.cc, configured=kw.pop('configured', True), speed_from_pcm=kw.pop('mode', 0), **kw)


def cue(s):
  tick(s, 0)
  s.cs.gasPressed = True
  tick(s, 0.01)
  tick(s, 0.10)
  s.cs.gasPressed = False
  return tick(s, 0.12)


def test_confirmed_set_uses_first_pcm_speed_once_not_peak_or_later_deceleration():
  s = context()
  assert cue(s) is None
  s.cs.cruiseState.enabled = True
  s.cs.cruiseState.speed = 50 / 3.6
  assert tick(s, 0.16) == pytest.approx(50)
  s.cs.cruiseState.speed = 49 / 3.6
  assert tick(s, 0.18) is None
  assert tick(s, 0.20) is None


@pytest.mark.parametrize(
  'change',
  [
    'brakePressed',
    'brakeHoldActive',
    'parkingBrake',
    'accFaulted',
    'canTimeout',
    'canValid',
    'main',
    'gear',
    'cancel',
    'manual',
    'option',
    'mode',
    'profile',
    'car',
  ],
)
def test_interruption_revokes_pending_speed(change):
  s = context()
  cue(s)
  kw = {}
  if change in ('brakePressed', 'brakeHoldActive', 'parkingBrake', 'accFaulted', 'canTimeout'):
    setattr(s.cs, change, True)
  elif change == 'canValid':
    s.cs.canValid = False
  elif change == 'main':
    s.cs.cruiseState.available = False
  elif change == 'gear':
    s.cs.gearShifter = 'park'
  elif change == 'cancel':
    s.cc.cruiseControl.cancel = True
  elif change == 'manual':
    kw['manual'] = True
  elif change == 'option':
    kw['configured'] = False
  elif change == 'mode':
    kw['mode'] = 1
  elif change == 'profile':
    s.cp.safetyConfigs[0].safetyParam = 1025
  elif change == 'car':
    s.cp.carFingerprint = 'HYUNDAI_IONIQ_5'
  tick(s, 0.14, **kw)
  s.cs.cruiseState.enabled = True
  s.cs.cruiseState.speed = 50 / 3.6
  assert tick(s, 0.16) is None


@pytest.mark.parametrize('speed', [0, 29, 161, float('nan'), float('inf')])
def test_invalid_confirmed_speed_cannot_change_local_setting(speed):
  s = context()
  cue(s)
  s.cs.cruiseState.enabled = True
  s.cs.cruiseState.speed = speed / 3.6
  assert tick(s, 0.16) is None


def test_no_response_expires_and_late_manual_stock_on_cannot_sync():
  s = context()
  cue(s)
  for n in range(13, 64):
    tick(s, n * 0.01)
  s.cs.cruiseState.enabled = True
  s.cs.cruiseState.speed = 50 / 3.6
  assert tick(s, 0.64) is None


def test_clock_stall_revokes_and_does_not_reuse_pressed_pedal():
  s = context()
  cue(s)
  s.cs.cruiseState.enabled = True
  s.cs.cruiseState.speed = 50 / 3.6
  assert tick(s, 1) is None


def test_resume_request_required_for_release_capture():
  s = context()
  s.cc.cruiseControl.resume = False
  cue(s)
  s.cs.cruiseState.enabled = True
  s.cs.cruiseState.speed = 50 / 3.6
  assert tick(s, 0.16) is None


def test_mid_hold_enable_needs_new_press():
  s = context()
  tick(s, 0, configured=False)
  s.cs.gasPressed = True
  tick(s, 0.01, configured=False)
  tick(s, 0.1)
  tick(s, 0.19)
  s.cs.gasPressed = False
  tick(s, 0.2)
  s.cs.cruiseState.enabled = True
  s.cs.cruiseState.speed = 50 / 3.6
  assert tick(s, 0.22) is None


@pytest.mark.parametrize("delay,expected", [(0.08, 50), (0.12, None)])
def test_existing_short_request_grace_is_observed_without_extending_confirmation(delay, expected):
  s = context()
  s.cc.cruiseControl.resume = False
  cue(s)
  tick(s, 0.18)
  s.cc.cruiseControl.resume = True
  tick(s, 0.12 + delay)
  s.cs.cruiseState.enabled = True
  s.cs.cruiseState.speed = 50 / 3.6
  assert tick(s, 0.14 + delay) == expected


def test_withdrawn_request_cannot_later_raise_target():
  s = context()
  cue(s)
  s.cc.cruiseControl.resume = False
  tick(s, 0.14)
  s.cs.cruiseState.enabled = True
  s.cs.cruiseState.speed = 50 / 3.6
  assert tick(s, 0.16) is None
