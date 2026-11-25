"""Run the production control-side capture with full cereal schema messages."""
import ast
import math
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from opendbc.car.hyundai import porter
from opendbc.car.hyundai.porter_pedal_set import PorterPedalCapture, pedal_capture_safe, pedal_set_profile_ready
from openpilot.cereal import car, log
from openpilot.common.constants import CV


@pytest.fixture
def s():
  source = Path(__file__).resolve().parents[1] / 'controlsd.py'
  tree = ast.parse(source.read_text())
  function = next(n for c in tree.body if isinstance(c, ast.ClassDef) and c.name == 'Controls'
                  for n in c.body if isinstance(n, ast.FunctionDef) and n.name == 'update_porter_pedal_set')
  env = {name: getattr(porter, name) for name in ('porter_gap_time_s', 'porter_auto_set_speed_valid',
                                                'porter_lead_reaction_s', 'porter_plan_allows_recovery')}
  env.update(math=math, CV=CV, DT_CTRL=.01, pedal_capture_safe=pedal_capture_safe, pedal_set_profile_ready=pedal_set_profile_ready)
  exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), env)
  values = {'AutoGasSyncSpeed': 1, 'SpeedFromPCM': 0, 'DisengageOnAccelerator': 0,
                'PorterGapUse': 1, 'PorterGap1': 40, 'PorterGap2': 80, 'PorterGap3': 120, 'PorterGap4': 180,
                'PorterLeadReactionTime': 60, 'CruiseButtonTest2': 25}
  cp = car.CarParams(carFingerprint='HYUNDAI_PORTER_II_EV', pcmCruise=True,
                     safetyConfigs=[{'safetyParam': 15489}])
  cs = car.CarState(canValid=True, gearShifter='drive', vEgo=54.664 / 3.6, vEgoCluster=58.125 / 3.6,
                    vCruiseCluster=58, vCluRatio=.94, wheelSpeeds={'fl': 54 / 3.6, 'rr': 54 / 3.6},
                    cruiseState={'enabled': True, 'available': True, 'speed': 47 / 3.6})
  cc = car.CarControl(enabled=True, hudControl={'setSpeed': 47 / 3.6})
  lp = log.LongitudinalPlan(speeds=[55 / 3.6, 56 / 3.6], vTargetNow=55 / 3.6, aTarget=.1,
                            tFollow=1.065, xState=0, trafficState=2)

  class SM(dict):
    logMonoTime = {'carState': 1_000_000_000}
    frame = 100
    good = True

    def all_checks(self, _):
      return self.good

  sm = SM(radarState=log.RadarState(leadOne={'status': True, 'dRel': 41.853, 'vRel': -3.709 / 3.6}),
          selfdriveState=log.SelfdriveState(personality='standard'))
  ctrl = NS(CP=cp, params=NS(get_int=lambda k: values.get(k, 0), get_bool=lambda k: bool(values.get(k, 0))),
            sm=sm, porter_pedal_capture=PorterPedalCapture(), porter_lead_tracker=porter.PorterLeadTracker())

  def tick(n, gas=False, nav=60):
    sm.logMonoTime['carState'] = 1_000_000_000 + n * 10_000_000
    sm.frame = 100 + n
    cs.gasPressed = gas
    cc.hudControl.setSpeed = 47 / 3.6  # Output from preceding GAP stage, recomputed each tick.
    env['update_porter_pedal_set'](ctrl, cs, cc, lp, nav)
    return cc.hudControl.porterPedalSetTime

  def release():
    tick(0)
    for n in range(1, 16):
      tick(n, True)
    return tick(16)

  return NS(ctrl=ctrl, cs=cs, cc=cc, lp=lp, sm=sm, values=values, tick=tick, release=release)


def test_exact_release_overrides_old_gap_cap_and_survives_schema_roundtrip(s):
  assert s.release() == 1_160_000_000
  assert s.cc.hudControl.porterPedalSetSpeed == 58
  assert s.cc.hudControl.setSpeed * 3.6 == pytest.approx(58)
  with car.CarControl.from_bytes(s.cc.to_bytes()) as restored:
    assert restored.hudControl.porterPedalSetTime == 1_160_000_000
    assert restored.hudControl.porterPedalSetSpeed == 58
  assert s.tick(17) == 1_160_000_000  # Original timestamp, never refreshed.
  s.cs.cruiseState.speed = 58 / 3.6
  assert s.tick(18) == 0
  assert s.tick(19) == 0


def test_active_capture_is_independent_of_standby_auto_set_option(s):
  s.ctrl.CP.safetyConfigs = [{'safetyParam': 1025}]
  assert s.release()


def test_release_at_matched_lead_speed_uses_dashboard_conversion(s):
  s.cs.vEgo, s.cs.vEgoCluster, s.cs.vCruiseCluster = 20., 77 / 3.6, 77.
  s.cs.cruiseState.speed = 70 / 3.6
  s.lp.speeds = [78 * .94 / 3.6, 80 * .94 / 3.6]
  s.sm['radarState'].leadOne.dRel, s.sm['radarState'].leadOne.vRel = 28., 0.
  s.tick(0, nav=85)
  for n in range(1, 16):
    s.tick(n, True, nav=85)
  assert s.tick(16, nav=85)
  assert s.cc.hudControl.porterPedalSetSpeed == 77
  s.sm['radarState'].leadOne.vRel = -2.
  assert not s.tick(17, nav=85)  # Conversion cannot override a closing-lead veto.


def test_cruise_helper_must_have_selected_release_speed_and_new_command_withdraws_it(s):
  s.cs.vCruiseCluster = 60
  assert not s.release()  # Explicit/remote input kept a different selection.
  s.cs.vCruiseCluster = 58
  assert not s.tick(17)  # It cannot become a late capture after recovery.
  s.tick(18, True)
  for n in range(19, 29):
    s.tick(n, True)
  assert s.tick(29)
  s.cs.vCruiseCluster = 65
  assert not s.tick(30)


@pytest.mark.parametrize('reason', ['brakePressed', 'brakeHoldActive', 'parkingBrake', 'canTimeout', 'accFaulted',
                                  'invalid_can', 'gear', 'cancel', 'manual', 'stock_off', 'main_off', 'disabled',
                                  'option', 'pcm', 'profile', 'other_car', 'direct_long', 'stale', 'stop', 'red',
                                  'falling_plan', 'nav', 'close_lead', 'lost_lead'])
def test_current_driver_and_deceleration_constraints_revoke_without_later_execution(s, reason):
  assert s.release()
  nav = 60
  if reason in ('brakePressed', 'brakeHoldActive', 'parkingBrake', 'canTimeout', 'accFaulted'):
    setattr(s.cs, reason, True)
  elif reason == 'invalid_can':
    s.cs.canValid = False
  elif reason == 'gear':
    s.cs.gearShifter = 'park'
  elif reason == 'cancel':
    s.cc.cruiseControl.cancel = True
  elif reason == 'manual':
    s.cs.buttonEvents = [{'type': 'decelCruise', 'pressed': True}]
  elif reason == 'stock_off':
    s.cs.cruiseState.enabled = False
  elif reason == 'main_off':
    s.cs.cruiseState.available = False
  elif reason == 'disabled':
    s.cc.enabled = False
  elif reason == 'option':
    s.values['AutoGasSyncSpeed'] = 0
  elif reason == 'pcm':
    s.values['SpeedFromPCM'] = 1
  elif reason == 'profile':
    s.ctrl.CP.safetyConfigs = [{'safetyParam': 15361}]
  elif reason == 'other_car':
    s.ctrl.CP.carFingerprint = 'HYUNDAI_IONIQ_5'
  elif reason == 'direct_long':
    s.ctrl.CP.openpilotLongitudinalControl = True
  elif reason == 'stale':
    s.sm.good = False
  elif reason == 'stop':
    s.lp.shouldStop = True
  elif reason == 'red':
    s.lp.trafficState = 1
  elif reason == 'falling_plan':
    s.lp.speeds = [55 / 3.6, 54 / 3.6]
  elif reason == 'nav':
    nav = 40
  elif reason == 'close_lead':
    s.sm['radarState'].leadOne.dRel = 7
  elif reason == 'lost_lead':
    s.ctrl.porter_lead_tracker.last_seen = s.sm.frame * .01
    s.sm['radarState'].leadOne.status = False
  assert s.tick(17, nav=nav) == 0
  # Re-enable all external conditions without another pedal input.
  s.cc.enabled = s.cs.canValid = s.cs.cruiseState.enabled = s.cs.cruiseState.available = True
  s.cc.cruiseControl.cancel = False
  s.cs.brakePressed = s.cs.brakeHoldActive = s.cs.parkingBrake = s.cs.canTimeout = s.cs.accFaulted = False
  s.cs.gearShifter, s.cs.buttonEvents = 'drive', []
  s.sm.good, s.lp.shouldStop, s.lp.trafficState = True, False, 2
  s.lp.speeds = [55 / 3.6, 56 / 3.6]
  s.sm['radarState'].leadOne.status, s.sm['radarState'].leadOne.dRel = True, 100
  s.values.update(AutoGasSyncSpeed=1, SpeedFromPCM=0)
  s.ctrl.CP.carFingerprint, s.ctrl.CP.openpilotLongitudinalControl = 'HYUNDAI_PORTER_II_EV', False
  s.ctrl.CP.safetyConfigs = [{'safetyParam': 15489}]
  assert s.tick(18) == 0


def test_no_ack_pending_expires_in_half_second(s):
  assert s.release()
  for n in range(17, 67):
    s.tick(n)
  assert s.tick(67) == 0
  assert s.tick(68) == 0


@pytest.mark.parametrize('field', ['stock', 'nav', 'selected', 'ratio'])
def test_invalid_speed_input_cannot_be_hidden_by_minimum_selection(s, field):
  assert s.release()
  if field == 'stock':
    s.cs.cruiseState.speed = math.nan
  elif field == 'selected':
    s.cs.vCruiseCluster = math.nan
  elif field == 'ratio':
    s.cs.vCluRatio = math.nan
  assert not s.tick(17, nav=math.nan if field == 'nav' else 60)


def test_rebase_changes_only_prior_memory_not_live_lead_or_next_deceleration(s):
  p = s.ctrl.porter_lead_tracker
  p.update(1, 60, 30, s.cs.vEgo, 100, 0, 2, adaptive=True, gap_time_s=1.065)
  p.decel_cap, p.decel_cap_time = 30, 1
  assert s.release()
  assert p.decel_cap is None
  assert p.adaptive_tracker.last_target == 58
  s.sm['radarState'].leadOne.dRel = 7
  assert s.tick(17) == 0
  p.adaptive_tracker.last_time = 1.16  # The real GAP stage runs every control tick.
  assert p.update(1.17, 60, 58, s.cs.vEgo, 7, -s.cs.vEgo, 2, adaptive=True, gap_time_s=1.065) == 30
