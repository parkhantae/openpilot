"""Physical lead motion must be compared with OEM settings in dashboard km/h."""
import math

import pytest

from opendbc.car.hyundai.porter import PorterLeadTracker, porter_lead_target_kph
from opendbc.car.hyundai.porter_pedal_set import pedal_capture_safe


def adaptive(*, ratio=.94, stock=None, distance=25., relative=0., target=100.):
  return PorterLeadTracker().update(
    0., target, 72. / ratio if stock is None else stock, 20., distance, relative, 1,
    gap_time_s=1., reaction_s=4., adaptive=True, cluster_ratio=ratio)


@pytest.mark.parametrize('ratio', [.9, .94, 1., 1.1])
def test_matched_lead_at_desired_physical_gap_does_not_demand_decrement(ratio):
  assert adaptive(ratio=ratio) == pytest.approx(72. / ratio)


def test_dashboard_steps_reserve_delivery_time_without_counting_speedometer_bias():
  # Lead 18m/s = 64.8 physical = 68.94 dashboard. With OEM 80, reserve
  # 12 one-km/h steps, not 16 based on physical km/h. Desired range stays 25m.
  ratio = .94
  steps = math.ceil(80. - 64.8 / ratio)
  assert steps == 12
  expected = (18. + (45. - 25.) / (4. + steps * .3)) * 3.6 / ratio
  assert adaptive(stock=80., distance=45., relative=-2.) == pytest.approx(expected)


@pytest.mark.parametrize('ratio', [.9, .94, 1., 1.1])
def test_close_lead_cap_stays_at_or_below_lead_in_dashboard_units(ratio):
  assert adaptive(ratio=ratio, distance=25., relative=-2.) == pytest.approx(64.8 / ratio)
  assert adaptive(ratio=ratio, distance=20., relative=-2.) < 64.8 / ratio
  assert adaptive(ratio=ratio, distance=8., relative=-20.) == 30.
  assert adaptive(ratio=ratio, target=30.) == 30.
  assert porter_lead_target_kph(100., 20., 25., -2., 1, gap_time_s=1., cluster_ratio=ratio) == pytest.approx(64.8 / ratio)


def test_capture_at_matched_speed_uses_same_units_and_still_rejects_closing_lead():
  args = dict(speed=72. / .94, target=80., ego=20., distance=25., relative=0.,
              visible=True, held=False, gap_time=1., reaction=4., spacing=.3, cluster_ratio=.94)
  assert pedal_capture_safe(**args)
  assert not pedal_capture_safe(**(args | dict(relative=-2.)))
  assert not pedal_capture_safe(**(args | dict(distance=20.)))
  assert not pedal_capture_safe(**(args | dict(target=70.)))


@pytest.mark.parametrize('ratio', [0., -.94, .49, 1.51, math.nan, math.inf])
@pytest.mark.parametrize('adaptive_mode', [False, True])
def test_invalid_ratio_blocks_recovery_and_cannot_release_previous_cap(ratio, adaptive_mode):
  p = PorterLeadTracker()
  low = p.update(0., 100., 80., 20., 15., -5., 1, gap_time_s=1., adaptive=adaptive_mode)
  held = p.update(.01, 100., 80., 20., 100., 2., 1, gap_time_s=1., adaptive=adaptive_mode, cluster_ratio=ratio)
  assert held <= low
  assert not p.recovery_ready
  if adaptive_mode:
    assert p.update(.02, 100., 80., 20., 100., 2., 1, adaptive=True) <= low
  assert porter_lead_target_kph(80., 20., 25., -2., 1, cluster_ratio=ratio) <= 30.
  assert not pedal_capture_safe(77., 80., 20., 100., 2., visible=True, held=False,
                                gap_time=1., reaction=4., spacing=.3, cluster_ratio=ratio)
