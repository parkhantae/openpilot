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
    self.assertEqual(self.step(.10), 1)
    self.assertEqual(self.step(.12), 0)
    self.assertEqual(self.step(.14), 0)
    self.assertIsNone(self.step(.16))
    self.assertEqual(self.p.status, "waiting_ack")

  def test_one_frame_per_stock_sample(self):
    self.assertEqual(self.step(0, key=10), 1)
    self.assertIsNone(self.step(.01, key=10))
    self.assertEqual(self.step(.02, key=11), 1)

  def test_no_feedback_stops_instead_of_retrying(self):
    self.step(0)
    self.step(.12)
    self.step(.14)
    self.assertIsNone(self.step(1))
    self.assertTrue(self.p.fault)
    self.assertIsNone(self.step(2))
    self.assertEqual((self.p.requests, self.p.timeouts), (1, 1))

  def test_ack_releases_early_and_obeys_gap(self):
    self.step(0)
    self.assertEqual(self.step(.04, current=51), 0)
    self.assertEqual(self.step(.06, current=51), 0)
    self.assertIsNone(self.step(.20, current=51))
    self.assertEqual(self.step(.32, current=51), 1)
    self.assertEqual((self.p.requests, self.p.acks), (2, 1))

  def test_deceleration(self):
    self.assertEqual(self.step(0, target=45), 2)
    self.assertEqual(self.step(.06, target=45, current=49), 0)
    self.assertEqual(self.p.acks, 1)

  def test_manual_input_wins_and_rearms(self):
    self.step(0)
    self.assertIsNone(self.step(.04, manual=True))
    self.assertIsNone(self.step(.06))
    self.assertEqual(self.step(.36), 1)

  def test_driver_disable_rearms_timeout(self):
    self.step(0)
    self.step(1)
    self.step(1.1, enabled=False)
    self.assertEqual(self.step(1.5), 1)

  def test_blocked_releases_but_never_presses(self):
    self.step(0)
    self.assertEqual(self.step(.04, blocked=True), 0)
    self.assertIsNone(self.step(.06, blocked=True))

  def test_cancel_once_per_request(self):
    self.assertEqual(self.step(0, cancel=True), 4)
    self.assertIsNone(self.step(.02, cancel=True))

  def test_wrong_direction_is_not_acknowledgement(self):
    self.step(0)
    self.assertEqual(self.step(.06, current=49), 0)
    self.assertTrue(self.p.fault)
    self.assertEqual(self.p.acks, 0)

  def test_invalid_inputs(self):
    for target in (0, 29, 161, float("nan"), float("inf")):
      self.setUp()
      self.assertIsNone(self.step(0, target=target))
    self.setUp()
    self.assertIsNone(self.step(0, press_seconds=0))

  def test_float32_speed_rounding_at_minimum(self):
    self.assertEqual(self.step(0, target=35, current=8.333333015441895 * 3.6), 1)
    self.setUp()
    self.assertIsNone(self.step(0, target=8.333333015441895 * 3.6, current=30))

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
    self.assertEqual(self.step(.06, target=51.6), 1)
    self.assertEqual(self.step(.12, target=51.4), 0)

  def test_real_no_response_still_latches(self):
    self.step(0, target=38, current=34)
    self.step(.12, target=38, current=34)
    self.step(.14, target=38, current=34)
    self.assertIsNone(self.step(1, target=38, current=34))
    self.assertIsNone(self.step(3, target=40, current=34))
    self.assertEqual((self.p.requests, self.p.timeouts), (1, 1))


if __name__ == "__main__":
  unittest.main()
