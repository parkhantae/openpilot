"""Distant vision outliers must not latch a lower OEM button target."""
import math

import pytest

from opendbc.car.hyundai.porter import PorterCruiseButtons, PorterLeadTracker
from opendbc.car.hyundai.porter_cancel import PorterLowSpeedCancel, porter_cancel_target


def vision_tick(tracker, now, **changes):
  # 67f/162 near48.1s: a single camera-lead speed dip while the plan rises.
  args = dict(target_kph=50., stock_target_kph=49., ego_speed=42.6 / 3.6,
              lead_distance=63.1, lead_relative_speed=-11.87 / 3.6, gap_level=2,
              adaptive=True, gap_time_s=1.009, reaction_s=6.5, cluster_ratio=.946,
              planner_accel_ready=True, lead_radar=False,
              lead_sample_id=1 + int(round(now * 100)) // 5)
  args.update(changes)
  return tracker.update(now, **args)


def prepared():
  tracker = PorterLeadTracker()
  for i in range(101):
    vision_tick(tracker, i * .01, lead_relative_speed=0., target_kph=49.)
  return tracker


@pytest.mark.parametrize('frames', [1, 2])
def test_one_or_two_vision_samples_do_not_emit_set_or_latch_low_target(frames):
  tracker = prepared()
  before = tracker.adaptive_tracker.last_target
  buttons = PorterCruiseButtons()
  emitted = []
  for i in range(frames * 5):
    now = 1.01 + i * .01
    target = vision_tick(tracker, now)
    assert target == pytest.approx(before)
    assert not tracker.recovery_ready  # No new RES permission during confirmation.
    emitted.append(buttons.update(now, target, 49., i // 2, enabled=True,
                                  stock_enabled=True, acceleration_ready=tracker.recovery_ready))
  assert 2 not in emitted
  recovered = vision_tick(tracker, 1.01 + frames * .05, lead_relative_speed=0.)
  assert recovered >= before
  assert recovered - before <= .018 + 1e-8


def test_persistent_distant_slow_lead_is_applied_after_confirmation():
  tracker = prepared()
  before = tracker.adaptive_tracker.last_target
  values = [vision_tick(tracker, 1.01 + i * .01) for i in range(21)]
  assert values[:15] == pytest.approx([before] * 15)
  assert values[15] < 48.
  # Confirmation stays valid during this episode; every lower sample does not
  # start a new delay after the first confirmed reduction.
  assert vision_tick(tracker, 1.22, lead_relative_speed=-12. / 3.6) < values[15]


def test_pending_target_cannot_issue_res_even_when_oem_has_not_caught_up():
  tracker = prepared()
  tracker.adaptive_tracker.last_target = 52.
  target = vision_tick(tracker, 1.01, target_kph=55.)
  assert target == 49.
  buttons = PorterCruiseButtons()
  assert buttons.update(1.01, target, 49., 1, enabled=True,
                        stock_enabled=True, acceleration_ready=False) is None


def test_sub_step_target_motion_does_not_restart_or_slow_normal_recovery():
  tracker = prepared()
  # The normal calculated target may wiggle below the preceding target without
  # asking for a whole OEM decrement. Do not replace it with stock speed.
  tracker.adaptive_tracker.last_target = 49.5
  value = vision_tick(tracker, 1.01, target_kph=49.4, lead_relative_speed=0.)
  assert value == pytest.approx(49.4)
  assert tracker.adaptive_tracker.vision_decel_since is None


def test_real_control_publish_passes_vision_provenance_and_new_sample_ids():
  import ast
  from pathlib import Path
  from types import SimpleNamespace as NS
  from opendbc.car.hyundai.porter import (
    porter_gap_time_s, porter_lead_reaction_s, porter_navi_target_kph, porter_plan_allows_recovery,
  )

  tree = ast.parse((Path(__file__).resolve().parents[5] / 'openpilot/selfdrive/controls/controlsd.py').read_text())
  node = next(n for n in ast.walk(tree) if isinstance(n, ast.If) and
              'lead_target_kph =' in ast.unparse(n) and
              "self.CP.carFingerprint == 'HYUNDAI_PORTER_II_EV'" in ast.unparse(n.test))
  code = compile(ast.Module(body=[node], type_ignores=[]), 'real_porter_vision_publish', 'exec')

  class SM(dict):
    frame = 0
    logMonoTime = {'radarState': 1}

    def all_checks(self, services):
      return True

  lead = NS(status=True, radar=False, dRel=63.1, vRel=0.)
  sm = SM(radarState=NS(leadOne=lead), selfdriveState=NS(personality=NS(raw=1)))
  tracker = PorterLeadTracker()
  obj = NS(CP=NS(carFingerprint='HYUNDAI_PORTER_II_EV'), sm=sm, porter_lead_tracker=tracker,
           params=NS(get_bool=lambda _: True, get_int=lambda key: 30 if key == 'CruiseButtonTest2' else 65))
  hud = NS(setSpeed=50. / 3.6)
  env = dict(self=obj, CC=NS(enabled=True), CS=NS(cruiseState=NS(enabled=True, speed=49. / 3.6),
                                             vEgo=42.6 / 3.6, vCluRatio=.946),
             speed_from_pcm=0, lp=NS(aTarget=.35, vTargetNow=43. / 3.6,
                                    speeds=[43. / 3.6, 46. / 3.6], shouldStop=False,
                                    xState=0, trafficState=2, tFollow=1.009),
             hudControl=hud, desired_kph=50., DT_CTRL=.01,
             CV=NS(MS_TO_KPH=3.6, KPH_TO_MS=1. / 3.6),
             porter_navi_target_kph=porter_navi_target_kph, porter_gap_time_s=porter_gap_time_s,
             porter_lead_reaction_s=porter_lead_reaction_s, porter_plan_allows_recovery=porter_plan_allows_recovery)
  for frame in range(206):
    sm.frame = frame
    sm.logMonoTime['radarState'] = 1 + frame // 5
    lead.vRel = 0. if frame < 201 else -11.87 / 3.6
    hud.setSpeed = 50. / 3.6
    exec(code, env)
    if frame >= 201:
      assert hud.setSpeed * 3.6 == pytest.approx(49.)
      assert not hud.porterAccelReady
      assert tracker.adaptive_tracker.vision_decel_since is not None


@pytest.mark.parametrize('changes', [
  dict(lead_distance=15.),
  dict(lead_distance=35.),
  dict(lead_relative_speed=-25. / 3.6),
  dict(planner_accel_ready=False),
  dict(recovery_allowed=False),
  dict(lead_radar=True),
  dict(lead_sample_id=None),
  dict(lead_sample_id=0),
  dict(lead_sample_id=math.nan),
])
def test_urgent_radar_unverified_or_falling_plan_never_delays_reduction(changes):
  tracker = prepared()
  before = tracker.adaptive_tracker.last_target
  assert vision_tick(tracker, 1.01, **changes) < before
  assert tracker.adaptive_tracker.vision_decel_since is None


def test_projected_danger_interrupts_pending_without_waiting():
  tracker = prepared()
  before = vision_tick(tracker, 1.01)
  assert vision_tick(tracker, 1.02, lead_distance=50., lead_relative_speed=-30. / 3.6) < before
  assert tracker.adaptive_tracker.vision_decel_since is None


def test_lower_navigation_or_planner_target_is_immediate_during_pending():
  tracker = prepared()
  vision_tick(tracker, 1.01)
  assert vision_tick(tracker, 1.02, target_kph=30.) == 30.


def test_duplicate_sample_cannot_confirm_and_expired_sample_is_not_deferred():
  tracker = prepared()
  before = tracker.adaptive_tracker.last_target
  for i in range(11):
    assert vision_tick(tracker, 1.01 + i * .01, lead_sample_id=1000) == before
    assert tracker.adaptive_tracker.vision_decel_samples == 1
  assert vision_tick(tracker, 1.12, lead_sample_id=1000) < before


def test_regressing_source_timestamp_cannot_use_previous_confirmation():
  tracker = prepared()
  vision_tick(tracker, 1.01, lead_sample_id=1000)
  assert vision_tick(tracker, 1.02, lead_sample_id=999) < 48.


def test_clock_gap_and_cruise_restart_discard_pending_confirmation():
  tracker = prepared()
  vision_tick(tracker, 1.01)
  vision_tick(tracker, 2.)
  assert tracker.adaptive_tracker.vision_decel_since is None
  tracker.observe_stock_cruise(False, valid=True)
  tracker.observe_stock_cruise(True, valid=True)
  assert tracker.adaptive_tracker is None


def test_driver_speed_sync_and_invalid_ratio_discard_pending_confirmation():
  tracker = prepared()
  vision_tick(tracker, 1.01)
  tracker.sync_driver_speed(50.)
  assert tracker.adaptive_tracker.vision_decel_since is None
  vision_tick(tracker, 1.02)
  vision_tick(tracker, 1.03, cluster_ratio=math.nan)
  assert tracker.adaptive_tracker.vision_decel_since is None
  assert not tracker.recovery_ready


def test_recorded_161_low_speed_cancel_remains_independent_and_immediate_after_hold():
  # 67f/161 at28.1s: ~50.7m lead, own39.8, relative-23.1km/h.
  tracker = prepared()
  cancel = PorterLowSpeedCancel()
  for i in range(32):
    now = 1.01 + i * .01
    target = vision_tick(tracker, now, ego_speed=39.8 / 3.6, lead_distance=50.7,
                         lead_relative_speed=-23.1 / 3.6, planner_accel_ready=False)
    assert target < 40.
    assert tracker.adaptive_tracker.vision_decel_since is None
    cancel_target = porter_cancel_target(40., 50., 57., 39.8 / 3.6, 50.7, -23.1 / 3.6, 2,
                                         lead_visible=True, gap_time_s=1.033, reaction_s=6.5,
                                         planner_now=43.)
    assert cancel_target == pytest.approx(16.7)
    assert cancel.update(now, cancel_target, eligible=True, cruise_enabled=True) == (i >= 30)
