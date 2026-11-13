import math

import pytest

from opendbc.car.hyundai.porter import PorterLeadTracker, porter_lead_target_kph
from opendbc.car.hyundai.porter_cancel import porter_cancel_target


def tick(p, t, *, distance=60.0, relative=-2.0, speed=20.0, target=100.0, stock=80.0, visible=True, fresh=True, gap=1.0):
  return p.update(t, target, stock, speed, distance, relative, 1, lead_visible=visible, recovery_allowed=fresh, gap_time_s=gap, reaction_s=4.0, adaptive=True)


def test_same_approach_slows_progressively_as_distance_shrinks():
  p = PorterLeadTracker()
  values = [tick(p, i * 0.05, distance=d) for i, d in enumerate((60, 45, 35, 25, 15))]
  assert values == pytest.approx([80.0, 80.0, 73.8, 64.8, 55.8])
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
  vals = [tick(p, n * 0.01, distance=100, relative=2, stock=60) for n in range(1, 102)]
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
