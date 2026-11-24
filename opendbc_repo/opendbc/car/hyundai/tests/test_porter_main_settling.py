"""A qualifying MAIN-settling release is bounded, interruptible and single-use."""
import pytest

from opendbc.car.hyundai.porter_main_set import PorterMainSet


def simulate(*, override=None, long_press=True, state=None):
  state = state or PorterMainSet(two_press=True, single_press=True, long_press=long_press)
  starts, sent = [], []
  for tick in range(150):
    # Reproduce 652/12: gas is already pressed when MAIN is switched on;
    # release follows only 270ms after MAIN, before its 500ms guard.
    args = dict(main_pressed=20 <= tick < 34, manual_button=0, blocked=False,
                request=tick >= 47, stock_enabled=False, configured=True,
                gas_pressed=10 <= tick < 47, release_eligible=True, sample_age_s=.004)
    if override:
      args.update(override(tick))
    before = state.requests
    value = state.update(tick * .01, tick // 2, **args)
    if state.requests != before:
      starts.append(tick)
    if value is not None:
      sent.append((tick, value))
  return state, starts, sent


def test_log652_main_during_pedal_sends_once_after_settling_not_before():
  state, starts, sent = simulate()
  assert starts == [70]
  assert sent == [(t, 2) for t in range(70, 82, 2)] + [(82, 0)]
  assert state.requests == 1 and state.timeouts == 1


@pytest.mark.parametrize('change', [
  {'blocked': True}, {'manual_button': 4}, {'main_pressed': True},
  {'configured': False}, {'request': False}, {'gas_pressed': True},
  {'release_eligible': False},
])
def test_override_during_settling_discards_original_release(change):
  _, starts, sent = simulate(override=lambda t: change if 55 <= t < 60 else {})
  assert starts == [] and sent == []


def test_deadline_expires_when_fresh_transmission_slots_are_missing():
  _, starts, sent = simulate(override=lambda t: {'sample_age_s': .009} if 47 <= t < 90 else {})
  assert starts == [] and sent == []


def test_retry_quiet_period_cannot_queue_a_settling_release():
  state = PorterMainSet(two_press=True, single_press=True, long_press=True)
  state.next_request = .75
  _, starts, sent = simulate(state=state)
  assert starts == [] and sent == []


def test_request_invalid_at_release_cannot_gain_extended_main_wait_later():
  _, starts, sent = simulate(override=lambda t: {'request': False} if 47 <= t < 50 else {})
  assert starts == [] and sent == []


def test_legacy_short_profile_retains_original_release_expiry():
  _, starts, sent = simulate(long_press=False)
  assert starts == [] and sent == []
