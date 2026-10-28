import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("porter_pulse", Path(__file__).resolve().parents[1] / "porter.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class TestPorterPulse(unittest.TestCase):
  def setUp(self):
    self.p = module.PorterCruiseButtons()

  def step(self, t, target=55, current=50, key=None, **kwargs):
    return self.p.update(t, target, current, round(t, 3) if key is None else key,
                         enabled=kwargs.pop("enabled", True), **kwargs)

  def test_press_is_at_least_observed_short_press_then_explicit_release(self):
    self.assertEqual(self.step(0), 1)
    self.assertEqual(self.step(.04), 1)
    self.assertEqual(self.step(.06), 0)
    self.assertEqual(self.step(.08), 0)
    self.assertIsNone(self.step(.10))
    self.assertEqual(self.p.status, "waiting_ack")

  def test_large_uptime_and_early_rx_cannot_add_fourth_press(self):
    # Segment 538 contains four-frame attempts despite the 60 ms clamp.
    # Early samples can exhaust the frame budget before the elapsed limit.
    for start in (0.0, 25.56, 2000.0, 100000.0):
      for target, button in ((55, 1), (45, 2)):
        with self.subTest(start=start, target=target):
          self.setUp()
          sent = [self.step(start + dt, target=target, key=i)
                  for i, dt in enumerate((0, .019, .038, .057, .078))]
          self.assertEqual(sent, [button, button, button, 0, 0])

  def test_segment_538_first_failed_request_transmission_times(self):
    # Rounded sendcan times relative to the first carState, without route IDs.
    # The early second CLU sample formerly allowed a fourth nonzero TX.
    times = (3.042276, 3.0523, 3.0713, 3.0918, 3.1117)
    sent = [self.step(t, target=35, current=34, key=i)
            for i, t in enumerate(times)]
    self.assertEqual(sent, [1, 1, 1, 0, 0])

  def test_duplicate_samples_do_not_consume_press_budget(self):
    self.assertEqual(self.step(2000, key=1), 1)
    self.assertIsNone(self.step(2000.01, key=1))
    self.assertEqual(self.step(2000.02, key=2), 1)
    self.assertIsNone(self.step(2000.03, key=2))
    self.assertEqual(self.step(2000.04, key=3), 1)
    self.assertIsNone(self.step(2000.05, key=3))
    self.assertEqual(self.step(2000.06, key=4), 0)

  def test_short_setting_limits_press_to_two_fresh_samples(self):
    sent = [self.step(dt, key=i, press_seconds=.04)
            for i, dt in enumerate((0, .015, .03, .05))]
    self.assertEqual(sent, [1, 1, 0, 0])

  def test_one_frame_per_stock_sample(self):
    self.assertEqual(self.step(0, key=10), 1)
    self.assertIsNone(self.step(.01, key=10))
    self.assertEqual(self.step(.02, key=11), 1)

  def test_single_missed_feedback_retries_after_bounded_gap(self):
    self.step(0)
    self.step(.12)
    self.step(.14)
    self.assertIsNone(self.step(.5))
    self.assertFalse(self.p.fault)
    self.assertEqual(self.p.status, "retry_wait")
    self.assertIsNone(self.step(.99))
    self.assertEqual(self.step(1.0), 1)
    self.assertEqual((self.p.requests, self.p.timeouts), (2, 1))

  def test_three_consecutive_misses_back_off_then_retry(self):
    for start in (0, 1.0, 2.0):
      self.assertEqual(self.step(start), 1)
      self.assertEqual(self.step(start + .12), 0)
      self.assertEqual(self.step(start + .14), 0)
      self.assertIsNone(self.step(start + .5))
    self.assertFalse(self.p.fault)
    self.assertEqual(self.p.status, "retry_backoff")
    self.assertEqual((self.p.requests, self.p.timeouts), (3, 3))
    self.assertIsNone(self.step(5.49))
    self.assertIsNone(self.step(5.5, key=550))
    self.assertEqual(self.step(5.51, key=550), 1)

  def test_complete_failed_group_changes_tx_slot_not_retry_rate_or_size(self):
    requests, outputs = [], []
    for tick in range(562):
      before = self.p.requests
      out = self.step(tick * .01, key=tick // 2)
      if before != self.p.requests:
        requests.append(round(tick * .01, 2))
      if out is not None:
        outputs.append((tick, out))
    self.assertEqual(requests, [0., 1., 2., 5.51])
    self.assertEqual(self.p.retry_sample_delay, .01)
    self.assertEqual([item for item in outputs if item[0] >= 550],
                     [(551, 1), (553, 1), (555, 1), (557, 0), (559, 0)])
    # Both slots still emit at most one frame for each 50 Hz stock sample.
    keys = [tick // 2 for tick, _ in outputs]
    self.assertEqual(len(keys), len(set(keys)))

  def test_acknowledged_delayed_slot_is_retained(self):
    self.p.retry_sample_delay = .01
    self.assertIsNone(self.step(0, key=0))
    self.assertEqual(self.step(.01, key=0), 1)
    self.assertIsNone(self.step(.02, key=1, current=51))
    self.assertEqual(self.step(.03, key=1, current=51), 0)
    self.assertIsNone(self.step(.04, key=2, current=51))
    self.assertEqual(self.step(.05, key=2, current=51), 0)
    self.assertEqual((self.p.acks, self.p.timeouts), (1, 0))
    self.assertEqual(self.p.retry_sample_delay, .01)

  def test_delayed_slot_does_not_delay_driver_cancel_or_pedal_release(self):
    for inhibit, expected in (({"cancel": True}, 4), ({"blocked": True}, 0),
                              ({"enabled": False}, 0), ({"manual": True}, None)):
      with self.subTest(inhibit=inhibit):
        self.setUp()
        self.p.retry_sample_delay = .01
        self.assertIsNone(self.step(0, key=0))
        self.assertEqual(self.step(.01, key=0), 1)
        # A new sample is immediately usable for an interrupt, without waiting.
        self.assertEqual(self.step(.02, key=1, **inhibit), expected)

  def test_delayed_slot_remembers_release_across_rx_loss(self):
    self.p.retry_sample_delay = .01
    self.assertIsNone(self.step(0, key=0))
    self.assertEqual(self.step(.01, key=0), 1)
    self.assertIsNone(self.p.update(.02, 55, 50, None, enabled=True))
    self.assertEqual(self.step(.03, key=1), 0)
    self.assertEqual(self.p.requests, 1)

  def test_rearm_restores_default_slot_and_no_automatic_enable(self):
    for inhibit in ({"manual": True}, {"enabled": False}):
      with self.subTest(inhibit=inhibit):
        self.setUp()
        self.p.retry_sample_delay = .01
        self.assertIsNone(self.step(0, key=0, **inhibit))
        self.assertEqual(self.p.retry_sample_delay, 0)
        self.assertEqual(self.p.requests, 0)
        self.assertEqual(self.step(.32, key=1), 1)

  def test_unavailable_delayed_slot_falls_back_after_bounded_wait(self):
    self.p.retry_sample_delay = .01
    # No control tick between stock samples: do not starve requests forever.
    for tick in range(5):
      self.assertIsNone(self.step(tick * .02, key=tick))
    self.assertEqual(self.p.requests, 0)
    self.assertEqual(self.step(.1, key=5), 1)
    self.assertEqual(self.p.retry_sample_delay, 0)
    self.assertEqual(self.step(.12, key=6), 1)
    self.assertEqual(self.step(.14, key=7), 1)
    self.assertEqual(self.step(.16, key=8), 0)
    self.assertEqual(self.step(.18, key=9), 0)
    self.assertEqual(self.p.requests, 1)
    self.assertIsNone(self.step(.6, key=10))
    self.assertEqual(self.p.timeouts, 1)

  def test_repeated_failed_groups_alternate_two_bounded_slots(self):
    slots = []
    previous_timeouts = 0
    for tick in range(1500):
      self.step(tick * .01, key=tick // 2)
      if self.p.timeouts != previous_timeouts:
        previous_timeouts = self.p.timeouts
        if previous_timeouts % 3 == 0:
          slots.append(self.p.retry_sample_delay)
    self.assertEqual(slots[:3], [.01, 0, .01])

  def test_ack_releases_early_and_obeys_gap(self):
    self.step(0)
    self.assertEqual(self.step(.04, current=51), 0)
    self.assertEqual(self.step(.06, current=51), 0)
    self.assertIsNone(self.step(.20, current=51))
    self.assertEqual(self.step(.32, current=51), 1)
    self.assertEqual((self.p.requests, self.p.acks), (2, 1))

  def test_ack_just_before_timeout_is_accepted(self):
    self.step(0)
    self.step(.12)
    self.step(.14)
    self.assertEqual(self.step(.49, current=51), 1)
    self.assertEqual((self.p.requests, self.p.acks, self.p.timeouts), (2, 1, 0))

  def test_ack_resets_consecutive_timeout_budget(self):
    self.step(0)
    self.step(.12)
    self.step(.14)
    self.step(.5)
    self.assertEqual(self.p.consecutive_timeouts, 1)
    self.assertEqual(self.step(1.0), 1)
    self.assertEqual(self.step(1.04, current=51), 0)
    self.assertEqual(self.p.consecutive_timeouts, 0)

  def test_five_kph_target_converges_with_five_one_kph_steps(self):
    now = 0.0
    current = 50
    for expected in range(51, 56):
      self.assertEqual(self.step(now, target=55, current=current), 1)
      current = expected
      self.assertEqual(self.step(now + .04, target=55, current=current), 0)
      self.assertEqual(self.step(now + .06, target=55, current=current), 0)
      now += .32
    self.assertIsNone(self.step(now, target=55, current=current))
    self.assertEqual((self.p.requests, self.p.acks), (5, 5))

  def test_deceleration(self):
    self.assertEqual(self.step(0, target=45), 2)
    self.assertEqual(self.step(.06, target=45, current=49), 0)
    self.assertEqual(self.p.acks, 1)

  def finish_deceleration(self):
    self.assertEqual(self.step(0, target=40, current=50), 2)
    self.assertEqual(self.step(.04, target=40, current=49), 0)
    self.assertEqual(self.step(.06, target=40, current=49), 0)

  def test_deceleration_to_acceleration_requires_continuous_higher_target(self):
    self.finish_deceleration()
    for tick in range(10, 60):
      self.assertIsNone(self.step(tick * .01, target=55, current=49))
    self.assertEqual(self.p.status, "accel_confirm")
    self.assertEqual(self.step(.60, target=55, current=49), 1)
    self.assertEqual(self.step(.64, target=55, current=50), 0)
    self.assertEqual(self.step(.66, target=55, current=50), 0)
    # Confirmation applies only to the reversal, not each following RES+.
    self.assertEqual(self.step(.92, target=55, current=50), 1)

  def test_short_high_target_blip_after_deceleration_never_sends_res(self):
    self.finish_deceleration()
    for tick in range(10, 40):
      self.assertIsNone(self.step(tick * .01, target=55, current=49))
    self.assertIsNone(self.step(.4, target=49, current=49))
    for tick in range(50, 100):
      self.assertIsNone(self.step(tick * .01, target=55, current=49))
    self.assertEqual(self.step(1., target=55, current=49), 1)

  def test_reversal_confirmation_never_delays_deceleration(self):
    self.finish_deceleration()
    self.assertIsNone(self.step(.1, target=55, current=49))
    self.assertEqual(self.step(.32, target=40, current=49), 2)
    self.assertEqual(self.step(.36, target=40, current=48), 0)
    self.assertEqual(self.step(.38, target=40, current=48), 0)
    self.assertEqual(self.step(.64, target=40, current=48), 2)

  def test_blocked_input_restarts_reversal_confirmation(self):
    self.finish_deceleration()
    self.step(.1, target=55, current=49)
    self.assertIsNone(self.step(.2, target=55, current=49, blocked=True))
    for tick in range(30, 80):
      self.assertIsNone(self.step(tick * .01, target=55, current=49))
    self.assertEqual(self.step(.8, target=55, current=49), 1)

  def test_observation_gap_cannot_confirm_acceleration(self):
    self.finish_deceleration()
    self.assertIsNone(self.step(.1, target=55, current=49))
    for tick in range(62, 112):
      self.assertIsNone(self.step(tick * .01, target=55, current=49))
    self.assertEqual(self.step(1.12, target=55, current=49), 1)

  def test_manual_or_disable_does_not_keep_old_reversal_gate(self):
    for interruption in ({"manual": True}, {"enabled": False}):
      with self.subTest(interruption=interruption):
        self.setUp()
        self.finish_deceleration()
        self.assertIsNone(self.step(.1, **interruption))
        self.assertEqual(self.step(.42, target=55, current=49), 1)

  def test_manual_input_wins_and_rearms(self):
    self.step(0)
    self.assertIsNone(self.step(.04, manual=True))
    self.assertIsNone(self.step(.06))
    self.assertEqual(self.step(.36), 1)

  def test_driver_disable_rearms_timeout(self):
    self.step(0)
    self.step(.5)
    self.step(.6, enabled=False)
    self.assertEqual(self.step(1.0), 1)

  def test_blocked_releases_but_never_presses(self):
    self.step(0)
    self.assertEqual(self.step(.04, blocked=True), 0)
    self.assertIsNone(self.step(.06, blocked=True))

  def test_interrupted_press_remembers_release_until_next_stock_frame(self):
    for interruption in ({"blocked": True}, {"enabled": False}, {"target": float("nan")},
                         {"current": 49}, {"cancel": True}):
      with self.subTest(interruption=interruption):
        self.setUp()
        self.assertEqual(self.step(0, key=10), 1)
        self.assertIsNone(self.step(.01, key=10, **interruption))
        self.assertIsNone(self.step(.02, key=10))
        self.assertEqual(self.step(.04, key=11), 0)
        self.assertIsNone(self.step(.06, key=12))
        self.assertEqual(self.p.requests, 1)

  def test_missing_stock_frame_cannot_discard_release(self):
    self.assertEqual(self.step(0, key=10), 1)
    self.assertIsNone(self.p.update(.01, 55, 50, None, enabled=True))
    self.assertIsNone(self.p.update(.02, 55, 50, None, enabled=True))
    self.assertEqual(self.step(.04, key=11), 0)
    self.assertIsNone(self.step(.06, key=12))

  def test_pending_release_precedes_a_new_request_after_long_gap(self):
    self.assertEqual(self.step(0, key=10), 1)
    self.assertIsNone(self.step(.01, key=10, blocked=True))
    self.assertEqual(self.step(2, key=11), 0)
    self.assertIsNone(self.step(2.02, key=12))
    self.assertEqual(self.step(2.32, key=13), 1)
    self.assertEqual((self.p.requests, self.p.timeouts), (2, 0))

  def test_manual_button_owns_bus_instead_of_pending_release(self):
    self.assertEqual(self.step(0, key=10), 1)
    self.assertIsNone(self.step(.01, key=10, blocked=True))
    self.assertIsNone(self.step(.04, key=11, manual=True))
    self.assertIsNone(self.step(.06, key=12))
    self.assertEqual(self.step(.36, key=13), 1)

  def test_interruption_without_a_press_does_not_send_release(self):
    self.assertIsNone(self.step(0, key=10, blocked=True))
    self.assertIsNone(self.step(.4, key=11, target=50))

  def test_release_transition_on_duplicate_frame_still_needs_release(self):
    self.assertEqual(self.step(0, key=10), 1)
    self.assertIsNone(self.step(.06, key=10))
    self.assertEqual(self.p.phase, "release")
    self.assertIsNone(self.step(.07, key=10, blocked=True))
    self.assertEqual(self.step(.08, key=11), 0)

  def test_cancel_once_per_request(self):
    self.assertEqual(self.step(0, cancel=True), 4)
    self.assertIsNone(self.step(.02, cancel=True))

  def test_wrong_direction_is_not_acknowledgement(self):
    self.step(0)
    self.assertEqual(self.step(.06, current=49), 0)
    self.assertTrue(self.p.fault)
    self.assertEqual(self.p.acks, 0)

  def test_invalid_inputs(self):
    for target in (0, 4, 29, 161, float("nan"), float("inf")):
      self.setUp()
      self.assertIsNone(self.step(0, target=target))
    self.setUp()
    self.assertIsNone(self.step(0, press_seconds=0))

  def test_float32_speed_rounding_at_minimum(self):
    self.assertEqual(self.step(0, target=35, current=8.333333015441895 * 3.6), 1)
    self.setUp()
    self.assertIsNone(self.step(0, target=4.9999999, current=5))

  def test_adjustment_at_stock_speed_floor(self):
    self.assertEqual(self.step(0, target=31, current=30), 1)
    self.setUp()
    self.assertEqual(self.step(0, target=30, current=31), 2)

  def test_no_automatic_engagement(self):
    self.assertIsNone(self.step(0, enabled=False))
    self.assertEqual(self.p.requests, 0)

  def test_time_reversal_stops(self):
    self.step(1)
    self.assertEqual(self.step(.9), 0)
    self.assertTrue(self.p.fault)

  def test_fractional_target_jitter_never_starts_or_latches(self):
    # Recorded failure at stock 44: planner toggled across 44.5, causing one
    # short RES frame followed by no acknowledgement and a latched stop.
    for i, target in enumerate((44.4, 44.6, 44.49, 44.51, 43.49, 43.51) * 30):
      self.assertIsNone(self.step(i * .02, target=target, current=44))
    self.assertEqual((self.p.requests, self.p.timeouts), (0, 0))
    self.assertFalse(self.p.fault)
    self.assertEqual(self.step(4, target=45, current=44), 1)

  def test_complete_step_starts_without_extra_debounce(self):
    for target, button in ((51, 1), (49, 2), (52.2, 1), (47.4, 2)):
      self.setUp()
      self.assertEqual(self.step(0, target=target), button)

  def test_boundary_noise_does_not_reset_ongoing_press(self):
    self.step(0, target=52)
    self.assertEqual(self.step(.02, target=51.6), 1)
    self.assertEqual(self.step(.04, target=51.4), 1)
    self.assertEqual(self.step(.06, target=51.6), 0)

  def test_target_crossing_does_not_truncate_unacknowledged_press(self):
    self.assertEqual(self.step(0, target=52, current=50), 1)
    self.assertEqual(self.step(.02, target=49, current=50), 1)
    self.assertEqual(self.step(.04, target=49, current=50), 1)
    self.assertEqual(self.step(.06, target=49, current=50), 0)

  def test_real_no_response_uses_bounded_retry_groups(self):
    for start in (0, 1.0, 2.0):
      self.step(start, target=38, current=34)
      self.step(start + .12, target=38, current=34)
      self.step(start + .14, target=38, current=34)
      self.assertIsNone(self.step(start + .5, target=38, current=34))
    self.assertIsNone(self.step(5.49, target=40, current=34))
    self.assertEqual((self.p.requests, self.p.timeouts), (3, 3))
    self.assertIsNone(self.step(5.5, target=40, current=34, key=550))
    self.assertEqual(self.step(5.51, target=40, current=34, key=550), 1)


if __name__ == "__main__":
  unittest.main()
