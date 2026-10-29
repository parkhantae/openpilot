import unittest

from opendbc.car.hyundai.porter_cancel import PorterCancelButtons


class TestCancelButtons(unittest.TestCase):
  def setUp(self):
    self.pulse = PorterCancelButtons()

  def tick(self, t, **kwargs):
    args = dict(requested=True, stock_enabled=True)
    args.update(kwargs)
    return self.pulse.update(t * .01, t // 2, **args)

  def test_press_release_and_repeated_no_off_feedback(self):
    output = [(t, b) for t in range(500) if (b := self.tick(t)) is not None]
    self.assertEqual(output[:4], [(0, 4), (2, 4), (4, 4), (6, 0)])
    self.assertEqual(output[4:8], [(57, 4), (59, 4), (61, 4), (62, 0)])
    starts = [t for i, (t, b) in enumerate(output) if b == 4 and (i == 0 or output[i-1][1] == 0)]
    self.assertGreaterEqual(starts[3] - starts[2], 300)

  def test_off_feedback_releases_and_stops(self):
    self.assertEqual(self.tick(0), 4)
    self.assertIsNone(self.tick(1, stock_enabled=False))
    self.assertEqual(self.tick(2, stock_enabled=False), 0)
    for t in range(3, 100):
      self.assertIsNone(self.tick(t, stock_enabled=False))
    self.assertFalse(self.pulse.busy)

  def test_manual_input_wins_and_release_waits_for_driver(self):
    self.assertEqual(self.tick(0), 4)
    for t in range(1, 10):
      self.assertIsNone(self.tick(t, manual=True))
    self.assertEqual(self.tick(10), 0)

  def test_live_request_removal_stops_new_cancel_pulses(self):
    self.assertEqual(self.tick(0), 4)
    self.assertEqual(self.tick(2, requested=False), 0)
    for t in range(3, 100):
      self.assertIsNone(self.tick(t, requested=False))

  def test_missing_template_does_not_transmit_or_forget_release(self):
    self.assertEqual(self.tick(0), 4)
    self.assertIsNone(self.pulse.update(.2, None, requested=True, stock_enabled=True, valid=False))
    self.assertEqual(self.pulse.update(.22, 11, requested=True, stock_enabled=True), 0)

  def test_known_acknowledged_slot_is_used_first(self):
    self.assertIsNone(self.tick(0, preferred_delay=.01))
    self.assertEqual(self.tick(1, preferred_delay=.01), 4)
    self.assertIsNone(self.tick(1, preferred_delay=.01))
    self.assertIsNone(self.tick(2, preferred_delay=.01))
    self.assertEqual(self.tick(3, preferred_delay=.01), 4)

  def test_delayed_slot_starvation_falls_back_after_100ms(self):
    results = []
    for tick in range(30):
      b = self.pulse.update(tick * .01, tick, requested=True, stock_enabled=True, preferred_delay=.01)
      if b is not None:
        results.append((tick, b))
    self.assertEqual(results[:4], [(10, 4), (11, 4), (12, 4), (13, 0)])

  def test_new_cancel_does_not_inherit_previous_backoff_or_trial_slot(self):
    for t in range(150):
      self.tick(t, preferred_delay=.01)
    self.assertEqual(self.pulse.requests, 3)
    self.tick(150, stock_enabled=False, preferred_delay=.01)
    self.assertIsNone(self.tick(152, preferred_delay=.01))
    self.assertEqual(self.tick(153, preferred_delay=.01), 4)
