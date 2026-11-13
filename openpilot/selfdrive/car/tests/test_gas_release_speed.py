from types import SimpleNamespace
import time

import pytest

from openpilot.cereal import car
from openpilot.common.constants import CV
from openpilot.common.params import Params
from openpilot.selfdrive.car import cruise


class Messages(dict):
  def __init__(self, cc):
    super().__init__(carControl=cc)
    self.alive = dict.fromkeys(('carrotMan', 'longitudinalPlan', 'radarState', 'drivingModelData'), False)
    self.seen = {'carrotMan': False}
    self.valid = {'carrotMan': False}
    self.recv_time = {'carrotMan': 0.}


@pytest.fixture(params=[True, False], ids=['porter-pcm', 'ioniq-long'])
def setup(request, tmp_path, monkeypatch):
  params = Params(str(tmp_path / 'params'))
  for key in params.all_keys():
    value = params.get_default_value(key)
    if value is not None:
      params.put(key, value)
  params.put_int('AutoGasSyncSpeed', 1)
  params.put_int('AutoCruiseControl', 1)
  params.put_int('CruiseButtonMode', 0)
  params.put_int('SpeedFromPCM', 0)
  monkeypatch.setattr(cruise, 'Params', lambda *args, **kwargs: params)
  monkeypatch.setattr(cruise, 'CommandReader', lambda _: SimpleNamespace(read=lambda **kw: None, is_repeat=False))
  pcm = request.param
  cp = car.CarParams(brand='hyundai', pcmCruise=pcm, openpilotLongitudinalControl=not pcm,
                     carFingerprint='HYUNDAI_PORTER_II_EV' if pcm else 'HYUNDAI_IONIQ_5')
  helper = cruise.VCruiseCarrot(cp)
  helper.v_cruise_kph = helper.v_cruise_cluster_kph = 70.
  helper.cruise_state_available_last = True
  helper._cruise_speed_initialized = True
  helper.enabled_last = True
  helper._gas_pressed_count = helper._brake_pressed_count = -10
  cs = car.CarState(canValid=True, gearShifter='drive', vEgo=70 * CV.KPH_TO_MS, vEgoCluster=70 * CV.KPH_TO_MS,
                    cruiseState={'enabled': True, 'available': True, 'speed': 70 * CV.KPH_TO_MS})
  cc = car.CarControl(enabled=True)
  sm = Messages(cc)
  logs = []
  add_log = helper._add_log

  def record(message):
    add_log(message)
    if message.startswith('Cruise speed from gas release:'):
      logs.append(message)

  helper._add_log = record

  def tick(gas, speed=85, frames=1):
    cs.gasPressed = gas
    cs.gas = 0.2 if gas else 0.
    cs.vEgo = cs.vEgoCluster = speed * CV.KPH_TO_MS
    for _ in range(frames):
      helper.update_v_cruise(cs, sm, True)
    return helper.v_cruise_kph

  return SimpleNamespace(params=params, helper=helper, cs=cs, cc=cc, sm=sm, tick=tick, logs=logs)


def test_release_uses_current_speed_instead_of_peak_and_does_not_follow_coasting(setup):
  s = setup
  assert s.tick(True, 100, 60) == 70  # Old implementation captured 100 here.
  assert s.tick(False, 85) == 85
  assert s.tick(False, 80, 80) == 85
  assert len(s.logs) == 1
  assert s.tick(True, 110, 60) == 85
  assert s.tick(False, 95) == 95
  assert len(s.logs) == 2


def test_release_below_original_setting_does_not_reduce_or_capture_peak(setup):
  s = setup
  s.tick(True, 100, 60)
  assert s.tick(False, 65) == 70
  assert not s.logs


def test_short_gas_tap_keeps_existing_preset_behavior(setup):
  s = setup
  s.tick(True, 75, 15)
  assert s.tick(False, 75) == 80
  assert not s.logs


def test_option_off_does_not_sync_on_hold_or_release(setup):
  s = setup
  s.params.put_int('AutoGasSyncSpeed', 0)
  assert s.tick(True, 100, 60) == 70
  assert s.tick(False, 85) == 70
  assert not s.logs


def test_enabling_mid_pedal_requires_a_new_press(setup):
  s = setup
  s.params.put_int('AutoGasSyncSpeed', 0)
  s.tick(True, 100, 60)
  s.params.put_int('AutoGasSyncSpeed', 1)
  s.tick(True, 100, 20)
  assert s.tick(False, 85) == 70
  assert not s.logs


def test_disabling_mid_pedal_revokes_capture(setup):
  s = setup
  s.tick(True, 100, 60)
  s.params.put_int('AutoGasSyncSpeed', 0)
  s.tick(True, 100, 20)
  assert s.tick(False, 85) == 70
  assert not s.logs


@pytest.mark.parametrize('interruption', ['brakePressed', 'brakeHoldActive', 'parkingBrake', 'accFaulted', 'canValid',
                                         'canTimeout', 'cc_enabled', 'cancel'])
def test_interruption_during_pedal_cannot_be_reused_after_recovery(setup, interruption):
  s = setup
  s.tick(True, 100, 45)
  if interruption == 'cc_enabled':
    s.cc.enabled = False
  elif interruption == 'cancel':
    s.cc.cruiseControl.cancel = True
  else:
    setattr(s.cs, interruption, interruption != 'canValid')
  s.tick(True, 100, 5)
  if interruption == 'cc_enabled':
    s.cc.enabled = True
  elif interruption == 'cancel':
    s.cc.cruiseControl.cancel = False
  else:
    setattr(s.cs, interruption, interruption == 'canValid')
  s.tick(True, 100, 15)
  s.tick(False, 85)
  assert not s.logs


def test_physical_speed_button_on_release_wins(setup):
  s = setup
  s.tick(True, 100, 60)
  s.cs.buttonEvents = [car.CarState.ButtonEvent(type='decelCruise', pressed=True),
                       car.CarState.ButtonEvent(type='decelCruise', pressed=False)]
  assert s.tick(False, 85) == 69
  assert not s.logs


def test_button_during_hold_revokes_later_release_capture(setup):
  s = setup
  s.tick(True, 100, 45)
  s.cs.buttonEvents = [car.CarState.ButtonEvent(type='accelCruise', pressed=True),
                       car.CarState.ButtonEvent(type='accelCruise', pressed=False)]
  s.tick(True, 100)
  s.cs.buttonEvents = []
  s.tick(True, 100, 15)
  assert s.tick(False, 85) == 71
  assert not s.logs


def test_model_speed_limit_remains_after_release_capture(setup):
  s = setup
  s.params.put_int('ApplyModelSpeed', -100)
  s.sm['drivingModelData'] = SimpleNamespace(action=SimpleNamespace(desiredVelocity=60 * CV.KPH_TO_MS))
  s.sm.alive['drivingModelData'] = True
  s.sm['carrotMan'] = SimpleNamespace(nRoadLimitSpeed=100, desiredSpeed=250, carrotCmdIndex=0, carrotCmd='', carrotArg='')
  s.sm.alive['carrotMan'] = s.sm.seen['carrotMan'] = s.sm.valid['carrotMan'] = True
  s.sm.recv_time['carrotMan'] = time.monotonic()
  s.tick(True, 100, 60)
  assert s.tick(False, 85) == pytest.approx(60)
  assert len(s.logs) == 1


def test_pcm_speed_mode_retains_vehicle_owned_setting(setup):
  s = setup
  if not s.helper.CP.pcmCruise:
    pytest.skip('PCM ownership applies to stock-cruise speed mode')
  s.params.put_int('SpeedFromPCM', 1)
  s.tick(True, 100, 60)
  assert s.tick(False, 85) == pytest.approx(70)
  assert not s.logs


def test_bluetooth_speed_button_on_release_wins(setup):
  s = setup
  s.tick(True, 100, 60)
  s.helper.bluetooth_commands.read = lambda **kw: 'decelCruise'
  assert s.tick(False, 85) == 69
  assert not s.logs


def test_carrot_speed_command_on_release_wins(setup):
  s = setup
  s.tick(True, 100, 60)
  s.sm['carrotMan'] = SimpleNamespace(nRoadLimitSpeed=100, desiredSpeed=250, carrotCmdIndex=1,
                                     carrotCmd='SPEED', carrotArg='60')
  s.sm.alive['carrotMan'] = s.sm.seen['carrotMan'] = s.sm.valid['carrotMan'] = True
  s.sm.recv_time['carrotMan'] = time.monotonic()
  assert s.tick(False, 85) == 60
  assert not s.logs


def test_close_lead_cancel_is_not_overridden_by_release_speed(setup):
  s = setup
  s.tick(True, 100, 60)
  s.helper.d_rel = 5
  assert s.tick(False, 85) == 70
  assert s.helper._activate_cruise < 0
  assert not s.logs


@pytest.mark.parametrize(('speed', 'expected'), [(85.3, 85), (85.7, 86), (200, 70)])
def test_release_rounding_and_existing_speed_bounds(setup, speed, expected):
  s = setup
  s.tick(True, 100, 60)
  assert s.tick(False, speed) == expected


def test_stock_cruise_off_during_pedal_revokes_porter_capture(setup):
  s = setup
  if not s.helper.CP.pcmCruise:
    pytest.skip('Direct longitudinal cruise does not require stock engagement')
  s.tick(True, 100, 45)
  s.cs.cruiseState.enabled = False
  s.tick(True, 100, 5)
  s.cs.cruiseState.enabled = True
  s.tick(True, 100, 15)
  s.tick(False, 85)
  assert not s.logs


def test_production_cruise_update_replaces_35_only_after_porter_stock_response(setup, monkeypatch):
  s = setup
  # The fixture also runs the Ioniq direct-long profile as an exclusion test.
  s.helper.CP.safetyConfigs = [car.CarParams.SafetyConfig(safetyModel='hyundai', safetyParam=15489)]
  s.params.put_bool('PorterAutoSetMain', True)
  s.helper.porter_auto_set_main = True
  s.params.put_int('AutoGasSyncSpeed', 0)
  s.helper.v_cruise_kph = s.helper.v_cruise_cluster_kph = 35
  s.cc.enabled = False
  s.cc.cruiseControl.resume = True
  s.cs.cruiseState.enabled = False
  clock = [0.0]
  monkeypatch.setattr('openpilot.selfdrive.car.cruise.time.monotonic', lambda: clock[0])
  for i in range(65):
    clock[0] = i * 0.01
    s.tick(True, 50.37)
  clock[0] = 0.65
  assert s.tick(False, 50.37) == 35
  clock[0] = 0.69
  s.cs.cruiseState.enabled = True
  s.cs.cruiseState.speed = 50 * CV.KPH_TO_MS
  s.cc.enabled = True
  expected = 50 if s.helper.CP.pcmCruise else 35
  assert s.tick(False, 50.37) == pytest.approx(expected)
  clock[0] = 0.71
  s.cs.cruiseState.speed = 49 * CV.KPH_TO_MS
  assert s.tick(False, 50) == pytest.approx(expected)
