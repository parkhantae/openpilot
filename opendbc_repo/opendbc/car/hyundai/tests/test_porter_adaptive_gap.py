import math
from types import SimpleNamespace

import pytest

from opendbc.car.hyundai.porter import PorterCruiseButtons, PorterLeadTracker, porter_lead_target_kph, porter_plan_allows_recovery
from opendbc.car.hyundai.porter_cancel import porter_cancel_target


def tick(p, t, *, distance=60.0, relative=-2.0, speed=20.0, target=100.0, stock=80.0, visible=True, fresh=True, gap=1.0):
  return p.update(t, target, stock, speed, distance, relative, 1, lead_visible=visible, recovery_allowed=fresh, gap_time_s=gap, reaction_s=4.0, adaptive=True)


def test_same_approach_slows_progressively_as_distance_shrinks():
  p = PorterLeadTracker()
  values = [tick(p, i * 0.05, distance=d) for i, d in enumerate((60, 45, 35, 25, 15))]
  assert values == pytest.approx([79.1181818182, 72.9818181818, 68.8909090909, 64.8, 55.8])
  assert all(a >= b for a, b in zip(values, values[1:], strict=False))
  # At the desired 25m distance the cap equals the lead's 64.8km/h.
  # Inside it the target falls below the lead speed to reopen the gap.


def test_same_distance_faster_approach_lowers_target_and_larger_gap_keeps_more_distance():
  slow = tick(PorterLeadTracker(), 0, distance=40, relative=-1)
  fast = tick(PorterLeadTracker(), 0, distance=40, relative=-5)
  wide = tick(PorterLeadTracker(), 0, distance=40, relative=-1, gap=2.0)
  assert fast < slow and wide < slow


def test_higher_ego_speed_increases_distance_at_equal_lead_speed():
  # Same lead20m/s, own20 vs25m/s and the same physical range.
  same = tick(PorterLeadTracker(), 0, speed=20, relative=0, distance=28)
  closing = tick(PorterLeadTracker(), 0, speed=25, relative=-5, distance=28)
  assert closing < same


def test_recovery_waits_for_stable_clear_gap_and_ramps_without_vehicle_falling_to_old_stock():
  p = PorterLeadTracker()
  start = tick(p, 0, distance=20, relative=-5, stock=60)
  vals = [tick(p, n * 0.01, distance=100, relative=2, stock=60) for n in range(1, 101)]
  assert all(v <= start + 1e-9 for v in vals[:50])
  assert 0 < vals[-1] - start <= 1.8 * 0.52 + 1e-9
  assert p.recovery_ready
  assert all(b - a <= 0.018 + 1e-9 for a, b in zip(vals, vals[1:], strict=False))


@pytest.mark.parametrize("visible,distance,fresh", [(False, 0, True), (True, math.nan, True), (True, 100, False)])
def test_dropout_and_invalid_data_cannot_raise_target(visible, distance, fresh):
  p = PorterLeadTracker()
  start = tick(p, 0, distance=20, relative=-5)
  for n in range(1, 40):
    assert tick(p, n * 0.01, distance=distance, visible=visible, fresh=fresh) <= start + 1e-9
    assert not p.recovery_ready


def test_lead_absence_recovers_only_after_hold_and_confirmation_then_ramps():
  p = PorterLeadTracker()
  start = tick(p, 0, distance=20, relative=-5)
  values = [tick(p, n * 0.01, distance=0, visible=False) for n in range(1, 141)]
  assert max(values[:110]) <= start + 1e-9
  assert min(values) < values[-1] <= min(values) + 1.8 * 0.31 + 1e-9


def test_lower_navigation_target_and_close_stopped_lead_are_not_delayed_by_smoothing():
  p = PorterLeadTracker()
  tick(p, 0, distance=100)
  assert tick(p, 0.01, distance=100, target=30) == 30
  assert tick(p, 0.02, distance=8, relative=-20) == 30
  assert porter_cancel_target(0, 70, None, 20, 8, -20, 1, lead_visible=True) == 0


def test_clock_gap_resets_recovery_and_mode_switch_does_not_reuse_old_cap():
  p = PorterLeadTracker()
  tick(p, 0, distance=20)
  assert tick(p, 1, distance=100, stock=50) <= 50
  assert not p.recovery_ready
  assert p.update(1.01, 100, 80, 20, 100, 0, 1, adaptive=False) == 100
  assert tick(p, 1.02, distance=100, stock=50) <= 50


def test_cancel_and_legacy_calculation_are_unchanged():
  assert porter_lead_target_kph(80, 20, 25, -5, 1) == 54
  assert porter_cancel_target(70, 70, None, 20, 8, -20, 1, lead_visible=True) == 0


def test_clock_gap_cannot_raise_a_previous_low_target_to_stock_speed():
  p = PorterLeadTracker()
  low = tick(p, 0, distance=15, relative=-5)
  assert tick(p, 1, distance=100, stock=80) <= low
  assert tick(p, 1.01, distance=100, stock=80) <= low
  assert not p.recovery_ready


def test_setting_catchup_time_starts_reduction_before_short_distance():
  p = PorterLeadTracker()
  # 90 -> 54 requires 36 accepted one-km/h steps, not an instant ECU target.
  target = p.update(0, 100, 90, 20, 70, -5, 1, gap_time_s=1., reaction_s=4., adaptive=True)
  assert target < 72  # begin reducing while the lead is still 70m ahead
  assert not p.recovery_ready


def test_slower_configured_button_spacing_reserves_more_approach_distance():
  values = []
  for interval in (.3, .6, 1.):
    values.append(PorterLeadTracker().update(0, 100, 90, 20, 70, -5, 1,
                  gap_time_s=1., reaction_s=4., adaptive=True, button_interval_s=interval))
  assert values[2] < values[1] < values[0] < 72


def test_lag_prediction_never_softens_a_cap_inside_the_selected_gap():
  for interval in (.3, .6, 1.):
    p = PorterLeadTracker()
    assert p.update(0, 100, 90, 20, 15, -5, 1, gap_time_s=1., reaction_s=4.,
                    adaptive=True, button_interval_s=interval) == pytest.approx(45.)


def test_opening_lead_recovers_faster_only_after_confirmation():
  p = PorterLeadTracker()
  values = [tick(p, n * .01, distance=100, relative=2, stock=60) for n in range(151)]
  assert max(b-a for a,b in zip(values[60:99],values[61:100],strict=True)) <= .018 + 1e-8
  assert values[150] - values[149] == pytest.approx(.03)
  assert p.recovery_ready
  # A closing lead immediately leaves the fast-recovery state.
  old = values[-1]
  new = tick(p, 1.51, distance=100, relative=-.1, stock=60)
  assert new-old <= .018 + 1e-8


def test_no_lead_fast_recovery_still_obeys_lower_navigation_limit():
  p = PorterLeadTracker()
  values = [tick(p, n * .01, distance=0, visible=False, stock=60) for n in range(151)]
  assert values[150] - values[149] == pytest.approx(.03)
  assert tick(p, 1.51, distance=0, visible=False, target=40, stock=60) == 40


def test_invalid_button_spacing_cannot_authorize_recovery():
  for interval in (0., -.3, float('nan'), float('inf')):
    p = PorterLeadTracker()
    results = [p.update(n*.01, 100, 60, 20, 100, 2, 1, adaptive=True, button_interval_s=interval)
               for n in range(151)]
    assert max(results) <= 60
    assert not p.recovery_ready


@pytest.mark.parametrize('interval', [.3, .6, 2.])
def test_confirmed_clear_road_recovery_respects_request_throughput(interval):
  p = PorterLeadTracker()
  values = [p.update(n * .01, 100, 60, 20, 0, 0, 1, lead_visible=False,
                    adaptive=True, button_interval_s=interval) for n in range(151)]
  assert values[-1] - values[-2] == pytest.approx(min(3., 1. / interval) * .01)


def test_recorded_closing_lead_cannot_reverse_deceleration_into_res():
  p = PorterLeadTracker()
  # Segment 634/65: ample range but the lead remains slower. Stock was 48
  # when a recovering 49km/h target incorrectly permitted RES+ at 30.43s.
  start = p.update(0., 47.94, 48., 46.6 / 3.6, 42.1, -2.43, 1,
                   gap_time_s=.52, reaction_s=7., adaptive=True)
  for n in range(1, 151):
    target = p.update(n * .01, 50., 48., 46.2 / 3.6, 39.9, -1.72, 1,
                      gap_time_s=.52, reaction_s=7., adaptive=True)
    assert target <= start
    assert not p.recovery_ready
  # A new urgent lower target is still immediate during the recovery block.
  assert p.update(1.51, 30., 48., 46.2 / 3.6, 39.9, -1.72, 1,
                  gap_time_s=.52, reaction_s=7., adaptive=True) == 30.


def test_closing_after_open_road_confirmation_revokes_res_permission_immediately():
  p = PorterLeadTracker()
  for n in range(151):
    tick(p, n * .01, distance=100., relative=2., stock=60.)
  assert p.recovery_ready
  assert tick(p, 1.51, distance=100., relative=-.3, stock=60.) <= 60.
  assert not p.recovery_ready
  for n in range(1, 50):
    tick(p, 1.51 + n * .01, distance=100., relative=2., stock=60.)
    assert not p.recovery_ready
  tick(p, 2.02, distance=100., relative=2., stock=60.)
  assert p.recovery_ready


def rising_plan(**changes):
  # 63c/369: the planner asks to accelerate while OEM stock remains at74.
  values = dict(aTarget=.5, vTargetNow=73.13 / 3.6, speeds=[73.13 / 3.6, 75. / 3.6, 77.18 / 3.6],
                shouldStop=False, xState=0, trafficState=2)
  values.update(changes)
  return SimpleNamespace(**values)


@pytest.mark.parametrize('valid,changes', [
  (False, {}), (True, {'aTarget': -.068}), (True, {'aTarget': 0.}),
  (True, {'speeds': [72. / 3.6]}), (True, {'speeds': [73.13 / 3.6, 76. / 3.6, 75. / 3.6, 80. / 3.6]}),
  (True, {'speeds': []}), (True, {'speeds': [float('nan')]}),
  (True, {'aTarget': float('inf')}), (True, {'vTargetNow': None}),
  (True, {'shouldStop': True}), (True, {'xState': 3}), (True, {'xState': 4}),
  (True, {'xState': 5}), (True, {'xState': 6}), (True, {'trafficState': 1}),
])
def test_stale_stopping_or_any_falling_forecast_cannot_allow_closing_lead_recovery(valid, changes):
  assert not porter_plan_allows_recovery(rising_plan(**changes), valid=valid)


def test_rising_plan_releases_recorded_stock_ceiling_despite_relative_speed_noise():
  assert porter_plan_allows_recovery(rising_plan(), valid=True)
  trackers = [PorterLeadTracker(), PorterLeadTracker()]
  buttons = [PorterCruiseButtons(), PorterCruiseButtons()]
  emitted = [[], []]
  results = [[], []]
  for n in range(301):
    # These short relative-speed sign changes used to repeatedly reset the
    # 0.5s timer and clamp a rising target back to OEM stock74.
    relative = (-1.2, .4, -.8, .7)[(n // 10) % 4]
    for i, tracker in enumerate(trackers):
      results[i].append(tracker.update(n * .01, 84., 74., 69.65 / 3.6, 74.86, relative, 2,
                                      gap_time_s=1.15, reaction_s=6., adaptive=True,
                                      planner_accel_ready=bool(i)))
      emitted[i].append(buttons[i].update(n * .01, results[i][-1], 74., n // 2, enabled=True,
                                          acceleration_ready=tracker.recovery_ready, press_seconds=.07,
                                          gap_seconds=.25, retry_limit=2, stock_enabled=True))
  assert max(results[0]) <= 74.
  assert max(results[1][:50]) <= 74.
  assert results[1][-1] > 78.
  assert 1 not in emitted[0]  # Old target never reaches a full RES+ step.
  assert 1 in emitted[1]     # Actual bounded button state machine can now request RES+.
  assert max(b - a for a, b in zip(results[1], results[1][1:], strict=False)) <= .018 + 1e-8
  # The same plan cannot permit recovery inside the projected closing gap.
  assert trackers[1].update(3.01, 84., 74., 69.65 / 3.6, 20., -4., 2,
                             gap_time_s=1.15, reaction_s=6., adaptive=True, planner_accel_ready=True) <= 74.
  assert not trackers[1].recovery_ready
  assert trackers[1].update(3.02, 30., 74., 69.65 / 3.6, 100., 1., 2,
                             gap_time_s=1.15, reaction_s=6., adaptive=True, planner_accel_ready=True) == 30.
