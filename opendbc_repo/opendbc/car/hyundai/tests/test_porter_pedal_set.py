"""Active-cruise capture: original pedal intent, finite CAN input, no blind retries."""
import math

import pytest

from opendbc.car.hyundai.porter_pedal_set import PorterPedalCapture, PorterPedalSet, pedal_capture_safe


def test_fresh_qualified_release_once_and_no_initial_held_pedal():
  p = PorterPedalCapture()
  for n in range(20):
    assert not p.observe(n * .01, True, True)
  assert not p.observe(.2, False, True)
  assert not p.observe(.21, True, True)
  for n in range(22, 31):
    assert not p.observe(n * .01, True, True)
  assert p.observe(.31, False, True)
  assert not p.observe(.32, False, True)


@pytest.mark.parametrize('reason', ['short', 'interrupted', 'clock', 'enable_mid_hold'])
def test_invalid_press_is_not_replayed_after_recovery(reason):
  p = PorterPedalCapture()
  p.observe(0, False, True)
  p.observe(.01, True, reason != 'enable_mid_hold')
  for n in range(2, 8 if reason == 'short' else 16):
    p.observe(n * .01, True, not (reason == 'interrupted' and n == 10))
  end = .09 if reason == 'short' else .5 if reason == 'clock' else .16
  assert not p.observe(end, False, True)
  assert not p.observe(end + .01, False, True)


def safe(**overrides):
  args = dict(speed=58, target=60, ego=54.664 / 3.6, distance=41.853, relative=-3.709 / 3.6,
              visible=True, held=True, gap_time=1.065, reaction=6, spacing=.3)
  args.update(overrides)
  return pedal_capture_safe(**args)


def test_recorded_654_releases_have_room_after_full_button_deceleration_budget():
  assert safe()
  assert safe(speed=47, target=51, ego=44.33 / 3.6, distance=26.115, relative=2.421 / 3.6, gap_time=1.02)
  # More time to deliver decrements must never create extra room.
  assert not safe(spacing=3)


@pytest.mark.parametrize('change', [dict(target=57), dict(distance=10), dict(relative=-8), dict(distance=math.nan),
                                  dict(ego=math.nan), dict(speed=29), dict(speed=161), dict(target=math.inf),
                                  dict(visible=False, held=True), dict(gap_time=30), dict(reaction=3)])
def test_current_limits_and_recent_lead_dropout_block_capture(change):
  assert not safe(**change)


def test_confirmed_no_lead_does_not_need_dummy_distance():
  assert safe(visible=False, held=False, distance=0, relative=0)


def tx(p, t, **kw):
  args = dict(stamp=1_000_000_000, speed=58, current=47, key=round(t * 100), enabled=True,
              blocked=False, manual=False, gas=False, sample_age_s=.004)
  args.update(kw)
  return p.update(round(t * 1e9), **args)


def test_one_press_three_fresh_frames_and_explicit_release_then_no_retry():
  p = PorterPedalSet()
  assert [tx(p, t) for t in (1, 1.01, 1.02, 1.03, 1.04, 1.05, 1.06)] == [2, None, 2, None, 2, 0, None]
  for n in range(107, 500):
    assert tx(p, n * .01) is None
  assert p.requests == p.timeouts == 1
  assert not p.busy


def test_first_tick_can_wait_for_next_fresh_clu_without_renewing_cue():
  p = PorterPedalSet()
  tx(p, .99, stamp=0, speed=0, key=7)
  assert tx(p, 1, key=7) is None
  assert p.busy
  assert tx(p, 1.01, key=8) == 2
  assert p.stamp == 1_000_000_000


def test_logged_float32_thirty_kph_stock_setting_is_not_treated_as_below_minimum():
  p = PorterPedalSet()
  assert tx(p, 1, current=29.999998855590825, speed=47) == 2
  assert p.requests == 1


def test_real_clock_bounds_end_press_even_if_counter_stalls():
  p = PorterPedalSet()
  assert tx(p, 1, key=7) == 2
  for n in range(101, 108):
    assert tx(p, n * .01, key=7) is None
  assert tx(p, 1.08, key=8) == 0
  assert p.frames == 1


@pytest.mark.parametrize('change', [dict(blocked=True), dict(manual=True), dict(gas=True), dict(enabled=False),
                                  dict(current=math.nan), dict(current=0), dict(sample_age_s=math.inf)])
def test_blocked_cue_is_consumed_not_executed_later(change):
  p = PorterPedalSet()
  assert tx(p, 1, **change) is None
  assert tx(p, 1.02) is None
  assert p.requests == 0


def test_stale_sample_and_expired_original_timestamp_never_start():
  p = PorterPedalSet()
  assert tx(p, 1, sample_age_s=.009) is None
  for n in range(101, 112):
    assert tx(p, n * .01, sample_age_s=.009) is None
  assert tx(p, 1.12) is None
  assert not p.busy
  p = PorterPedalSet()
  assert tx(p, 1.101) is None
  assert p.requests == 0


@pytest.mark.parametrize('change', [dict(blocked=True), dict(manual=True), dict(gas=True), dict(enabled=False),
                                  dict(stamp=0, speed=0), dict(current=46)])
def test_override_or_wrong_direction_stops_remaining_press(change):
  p = PorterPedalSet()
  assert tx(p, 1) == 2
  result = tx(p, 1.02, **change)
  assert result == (None if change.get('manual') else 0)
  # Manual input remains untouched; only a neutral release may follow it.
  assert tx(p, 1.04) in (None, 0)
  assert tx(p, 1.06) is None
  assert p.requests == 1


def test_ack_requires_current_speed_capture_and_ends_remaining_frames():
  p = PorterPedalSet()
  assert tx(p, 1) == 2
  assert tx(p, 1.02, current=48) == 2
  assert p.acks == 0
  assert tx(p, 1.04, current=58, stamp=0, speed=0) == 0
  assert p.acks == 1
  assert not p.busy


def test_quiet_time_is_measured_at_new_release_not_queued_until_start():
  p = PorterPedalSet()
  for n in range(100, 151):
    tx(p, n * .01)
  for n in range(151, 406):
    tx(p, n * .01, stamp=4_000_000_000 if n >= 400 else 0, speed=58)
  assert p.requests == 1
  assert tx(p, 4.06, stamp=4_060_000_000) == 2
  assert p.requests == 2


def test_backwards_or_stalled_controller_clock_aborts_without_replaying():
  for t in (.99, 1.2):
    p = PorterPedalSet()
    assert tx(p, 1) == 2
    assert tx(p, t) == 0
    assert tx(p, t + .02) is None
    assert p.requests == 1
