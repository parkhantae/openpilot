import unittest
from opendbc.car.hyundai.porter_main_set import PorterMainSet


class TestPorterMainSet(unittest.TestCase):
  def setUp(self):
    self.state = PorterMainSet()

  def tick(self, tick, **kw):
    args = dict(main_pressed=False, manual_button=0, blocked=False, request=True,
                stock_enabled=False, configured=True)
    args.update(kw)
    return self.state.update(tick * .01, tick // 2 if tick % 2 == 0 else None, **args)

  def arm(self):
    self.tick(0, main_pressed=True)
    self.tick(2)

  def test_no_main_or_disabled_setting_never_starts(self):
    for t in range(200):
      self.assertIsNone(self.tick(t))
    self.state = PorterMainSet()
    for t in range(200):
      self.assertIsNone(self.tick(t, configured=False, main_pressed=t < 10))

  def test_set_only_confirmation_pulse_release_and_retry_limit(self):
    self.arm()
    output = [(t, b) for t in range(3, 160) if (b := self.tick(t)) is not None]
    self.assertEqual(output[:4], [(52, 2), (54, 2), (56, 2), (58, 0)])
    self.assertTrue(all(b in (0, 2) for _, b in output))
    self.assertGreaterEqual(output[4][0] - output[0][0], 100)

  def test_cancel_brake_main_off_and_live_off_disarm(self):
    for guard in (dict(manual_button=4), dict(blocked=True), dict(main_pressed=True), dict(configured=False)):
      self.setUp()
      self.arm()
      self.tick(4, **guard)
      self.tick(6)
      self.assertFalse(self.state.armed)
      for t in range(7, 90):
        self.assertIsNone(self.tick(t))

  def test_gas_or_low_speed_request_loss_resets_confirmation(self):
    self.arm()
    for t in range(3, 60):
      self.tick(t, request=t < 40)
    for t in range(60, 110):
      self.assertIsNone(self.tick(t))
    self.assertEqual(self.tick(110), 2)

  def test_stock_engagement_and_interruption_release(self):
    self.arm()
    for t in range(3, 53):
      self.tick(t)
    self.assertEqual(self.tick(54, stock_enabled=True), 0)
    for t in range(55, 100):
      self.assertIsNone(self.tick(t, stock_enabled=True))

  def test_stream_gap_requires_new_main(self):
    self.arm()
    self.assertIsNone(self.tick(50))
    self.assertFalse(self.state.armed)

  def test_manual_button_interrupt_does_not_transmit_release_over_driver(self):
    self.arm()
    for t in range(3, 53):
      self.tick(t)
    self.assertIsNone(self.tick(54, manual_button=4))
    self.assertIsNone(self.tick(56, manual_button=4))
    self.assertEqual(self.tick(58), 0)
    self.assertFalse(self.state.armed)
