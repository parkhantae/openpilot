"""Bounded deceleration-only recovery; no hardware or live CAN."""

import pytest

from opendbc.car.hyundai.porter import PorterCruiseButtons


def tick(b, i, *, target=47.01, current=58, option=True, **kw):
  return b.update(
    i * 0.01,
    target,
    current,
    kw.pop("frame_key", i // 2),
    enabled=kw.pop("enabled", True),
    stock_enabled=kw.pop("stock_enabled", True),
    press_seconds=0.06,
    gap_seconds=0.25,
    retry_limit=kw.pop("retry_limit", 2),
    decel_recovery=option,
    **kw,
  )


def exhaust(b, **kw):
  for i in range(300):
    tick(b, i, **kw)
  assert b.retry_exhausted


def test_exactly_one_extra_press_after_three_seconds_then_stops():
  b = PorterCruiseButtons()
  starts = []
  previous = 0
  exhausted = None
  output = []
  for i in range(2000):
    value = tick(b, i)
    if b.requests != previous:
      starts.append(i * 0.01)
      previous = b.requests
    if b.retry_exhausted and exhausted is None:
      exhausted = i * 0.01
    if value is not None:
      output.append((i * 0.01, value))
  assert b.requests == b.timeouts == 4
  assert starts[3] - exhausted >= 3 - 1e-9
  extra = [(t, value) for t, value in output if t >= starts[3]]
  assert [value for _, value in extra if value] == [2, 2, 2]
  assert any(value == 0 for _, value in extra)
  assert extra[-1][0] - starts[3] < 0.12
  assert b.retry_exhausted and b.recovery_used and b.unavailable


@pytest.mark.parametrize("option,budget,target,count", [(False, 2, 47, 3), (True, 0, 47, 1), (True, 1, 47, 2), (True, 2, 65, 3)])
def test_default_off_small_budgets_and_acceleration_cannot_use_extra_attempt(option, budget, target, count):
  b = PorterCruiseButtons()
  for i in range(1500):
    tick(b, i, target=target, option=option, retry_limit=budget)
  assert b.requests == count
  assert not b.recovery_used


@pytest.mark.parametrize("condition", ["blocked", "option_off", "target_equal", "target_higher", "missing_frame", "invalid_target", "cancel"])
def test_pending_request_is_discarded_on_condition_loss_and_never_replayed(condition):
  b = PorterCruiseButtons()
  exhaust(b)
  assert b.recovery_due is not None
  kw = {
    "blocked": {"blocked": True},
    "option_off": {"option": False},
    "target_equal": {"target": 58},
    "target_higher": {"target": 65},
    "missing_frame": {"frame_key": None},
    "invalid_target": {"target": float("nan")},
    "cancel": {"cancel": True},
  }[condition]
  tick(b, 300, **kw)
  for i in range(301, 1500):
    tick(b, i)
  assert b.requests == 3
  assert b.recovery_due is None


def test_missing_fresh_slot_expires_instead_of_firing_later():
  b = PorterCruiseButtons()
  exhaust(b)
  for i in range(300, 1500):
    tick(b, i, frame_key=149 if i < 650 else i // 2)
  assert b.requests == 3 and not b.recovery_used


def test_clock_gap_discards_pending_authority():
  b = PorterCruiseButtons()
  exhaust(b)
  for i in range(500, 1500):
    tick(b, i)
  assert b.requests == 3


def test_success_keeps_warning_and_deceleration_only_until_manual_input():
  b = PorterCruiseButtons()
  exhaust(b)
  for i in range(300, 1000):
    current = 57 if b.requests == 4 else 58
    value = tick(b, i, current=current, target=65 if b.requests == 4 else 47)
    # The first recovery press still has a low target; a subsequent raised
    # target interrupts or completes that press without authorizing RES+.
    assert value != 1
  assert b.requests == 4 and b.unavailable and b.decel_only
  tick(b, 1000, manual=True)
  assert not b.unavailable
  assert b.recovery_used  # A physical button does not replenish the extra token.


def test_acknowledged_extra_press_can_continue_deceleration_but_never_accelerates():
  b = PorterCruiseButtons()
  current = 58
  for i in range(1500):
    if b.requests >= 4 and b.phase == "press":
      current = b.baseline - 1
    value = tick(b, i, current=current, target=65 if i >= 800 else 47)
    assert value != 1
  assert b.acks > 1 and b.decel_only and b.unavailable


def test_live_off_interrupts_trial_and_releases_without_later_retry():
  b = PorterCruiseButtons()
  exhaust(b)
  for i in range(300, 700):
    tick(b, i, option=b.requests < 4)
  assert b.requests == 4 and b.retry_exhausted
  for i in range(700, 1500):
    assert tick(b, i) != 2


def test_ack_at_the_target_is_counted_before_deceleration_only_stops_new_requests():
  b = PorterCruiseButtons()
  for i in range(1500):
    value = tick(b, i, current=57 if b.requests == 4 else 58, target=57)
    assert value != 1
  assert b.requests == 4 and b.acks == 1 and b.decel_only


def test_token_replenishes_only_on_actual_stock_off():
  b = PorterCruiseButtons()
  for i in range(900):
    tick(b, i)
  assert b.requests == 4
  tick(b, 900, manual=True)
  for i in range(901, 1900):
    tick(b, i)
  assert b.requests == 7  # Three ordinary misses, no second extra press.
  tick(b, 1900, enabled=False, stock_enabled=False)
  assert not b.recovery_used
  for i in range(1901, 3000):
    tick(b, i)
  assert b.requests == 11


def test_enabling_after_an_old_failure_does_not_create_queued_authority():
  b = PorterCruiseButtons()
  exhaust(b, option=False)
  for i in range(300, 1500):
    tick(b, i)
  assert b.requests == 3


def test_bunched_control_frames_cannot_skip_three_seconds_of_actual_dispatch_time():
  b = PorterCruiseButtons()
  for i in range(1500):
    tick(b, i, tx_now_s=i * 0.001)
  assert b.requests == 3
  assert not b.recovery_used


@pytest.mark.parametrize('acceleration_misses', [1, 2])
def test_mixed_acceleration_failures_do_not_count_as_three_deceleration_failures(acceleration_misses):
  b = PorterCruiseButtons()
  for i in range(1500):
    target = 65 if i < acceleration_misses * 100 - 25 else 47
    tick(b, i, target=target)
  assert b.requests == 3 and b.decel_timeouts == 3 - acceleration_misses
  assert not b.recovery_used


@pytest.mark.parametrize("allowed,mode,expected", [(True, 0, 4), (False, 0, 3), (True, 2, 3)])
def test_actual_message_adapter_requires_live_permission_and_pcm_zero(allowed, mode, expected):
  from opendbc.car.hyundai.tests.test_porter_controller import TestPorterMessagePath

  TestPorterMessagePath.setUpClass()
  fixture = TestPorterMessagePath()
  fixture.setUp()
  fixture.controller.porter_main_params.get_bool = lambda key: key == "PorterDecelRetry"
  fixture.controller.speed_from_pcm = mode
  fixture.cc.hudControl.porterRecoveryAllowed = allowed
  outputs = []
  for i in range(1400):
    outputs.extend(fixture.tick(i))
  # The fixture starts with target55 > stock50. Use a deceleration target for
  # this new stock session rather than treating RES+ as eligible for recovery.
  assert fixture.controller.porter_buttons.requests == 3
  fixture.setUp()
  fixture.controller.porter_main_params.get_bool = lambda key: key == "PorterDecelRetry"
  fixture.controller.speed_from_pcm = mode
  fixture.cc.hudControl.porterRecoveryAllowed = allowed
  fixture.cc.hudControl.setSpeed = 40 / 3.6
  outputs = []
  for i in range(1400):
    outputs.extend(fixture.tick(i))
  assert fixture.controller.porter_buttons.requests == expected
  assert all(value in (0, 2) for value in outputs)
