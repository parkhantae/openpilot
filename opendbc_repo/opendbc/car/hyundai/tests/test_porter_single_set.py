"""One pedal release authorizes one bounded press, never a queued second."""
import unittest

from opendbc.car.hyundai.porter_main_set import PorterMainSet


class TestPorterSingleSet(unittest.TestCase):
  def run_release(self, *, gas=None, stock=None, override=None):
    state = PorterMainSet(two_press=True, single_press=True)
    starts, outputs = [], []
    for tick in range(1000):
      gas_on = gas(tick) if gas else 20 <= tick < 100
      args = dict(main_pressed=tick < 2, manual_button=0, blocked=False,
                  request=not gas_on, stock_enabled=stock(tick) if stock else False,
                  configured=True, gas_pressed=gas_on)
      if override:
        args.update(override(tick))
      before = state.requests
      button = state.update(tick * .01, tick // 2, **args)
      if state.requests != before:
        starts.append(tick)
      if button is not None:
        outputs.append((tick, button))
    return state, starts, outputs

  def test_release_starts_on_next_sample_and_never_repeats_without_new_pedal(self):
    state, starts, outputs = self.run_release()
    self.assertEqual(starts, [100])
    self.assertEqual(outputs, [(100, 2), (102, 2), (104, 2), (106, 0)])
    self.assertEqual(state.pair_remaining, 0)
    self.assertEqual(state.timeouts, 1)

  def test_every_eligible_new_pedal_cycle_gets_one_press_even_after_no_response(self):
    _, starts, outputs = self.run_release(
      gas=lambda t: 20 <= t < 100 or 420 <= t < 450 or 800 <= t < 820)
    self.assertEqual(starts, [100, 450, 820])
    for start in starts:
      self.assertEqual([x for x in outputs if start <= x[0] < start + 100],
                       [(start, 2), (start + 2, 2), (start + 4, 2), (start + 6, 0)])

  def test_stock_on_finishes_with_release_without_extra_set(self):
    for engage_at, expected in ((101, [(100, 2), (102, 0)]),
                                (103, [(100, 2), (102, 2), (104, 0)])):
      with self.subTest(engage_at=engage_at):
        state, starts, outputs = self.run_release(stock=lambda t,e=engage_at: t >= e)
        self.assertEqual(starts, [100])
        self.assertEqual(outputs, expected)
        self.assertEqual(state.acks, 1)

  def test_manual_or_blocked_inputs_abort_remaining_press(self):
    for change in ({'blocked': True}, {'manual_button': 4}, {'main_pressed': True},
                   {'configured': False}, {'request': False}, {'release_eligible': False}):
      with self.subTest(change=change):
        state, starts, outputs = self.run_release(override=lambda t,c=change: c if 101 <= t < 110 else {})
        self.assertEqual(starts, [100])
        self.assertEqual([x for x in outputs if x[1] == 2], [(100, 2)])
        self.assertEqual(state.pair_remaining, 0)

  def test_short_pedal_and_cooldown_cues_do_not_queue_an_engagement(self):
    _, starts, _ = self.run_release(gas=lambda t: 20 <= t < 25 or 80 <= t < 100 or
                                   200 <= t < 220 or 800 <= t < 820)
    self.assertEqual(starts, [100, 820])

  def test_off_option_and_main_off_never_send_automatic_set(self):
    for change in ({'configured': False}, {'main_pressed': False}):
      with self.subTest(change=change):
        _, starts, outputs = self.run_release(override=lambda t,c=change: c)
        self.assertEqual(starts, [])
        self.assertEqual(outputs, [])

  def test_release_between_samples_waits_only_for_next_timely_sample(self):
    _, starts, _ = self.run_release(gas=lambda t: 20 <= t < 101)
    self.assertEqual(starts, [102])  # 10ms to the next sample, no added dwell.

  def test_new_pedal_rearms_after_brake_or_cancel_with_main_still_on(self):
    for change in ({'blocked': True}, {'manual_button': 4}):
      with self.subTest(change=change):
        _, starts, _ = self.run_release(
          gas=lambda t: 20 <= t < 100 or 420 <= t < 450,
          override=lambda t,c=change: c if 200 <= t < 210 else {})
        self.assertEqual(starts, [100, 450])
