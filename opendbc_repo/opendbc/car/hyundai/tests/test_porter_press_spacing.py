import unittest

from opendbc.car.hyundai.porter import PorterCruiseButtons
from opendbc.car.hyundai.porter_main_set import PorterMainSet


class TestPorterPressSpacing(unittest.TestCase):
  def speed_tick(self, state, now, key, **overrides):
    args = dict(enabled=True, target=45., current=50., frame_key=key)
    args.update(overrides)
    return state.update(now, **args)

  def ready_main(self):
    state = PorterMainSet(two_press=True, single_press=True, long_press=True)
    for tick in range(80):
      state.update(tick * .01, tick // 2, main_pressed=tick < 2,
                   manual_button=0, blocked=False, request=True,
                   stock_enabled=False, configured=True, gas_pressed=tick >= 20,
                   sample_age_s=0.)
    return state

  def main_tick(self, state, now, key, **overrides):
    args = dict(main_pressed=False, manual_button=0, blocked=False,
                request=True, stock_enabled=False, configured=True,
                gas_pressed=False, sample_age_s=0.)
    args.update(overrides)
    return state.update(now, key, **args)

  def test_speed_drops_bunched_sample_without_replaying_it(self):
    for start in (0., 100000.):
      for target, button in ((45., 2), (55., 1)):
        with self.subTest(start=start, button=button):
          state = PorterCruiseButtons()
          self.assertEqual(self.speed_tick(state, start, 0, target=target), button)
          self.assertIsNone(self.speed_tick(state, start + .01, 1, target=target))
          self.assertIsNone(self.speed_tick(state, start + .02, 1, target=target))
          self.assertEqual(self.speed_tick(state, start + .04, 2, target=target), button)
          self.assertEqual(self.speed_tick(state, start + .06, 3, target=target), 0)
          self.assertEqual(state.press_count, 2)

  def test_main_drops_bunched_sample_without_extending_deadline(self):
    state = self.ready_main()
    self.assertEqual(self.main_tick(state, .80, 40), 2)
    self.assertIsNone(self.main_tick(state, .81, 41))
    self.assertIsNone(self.main_tick(state, .82, 41))
    self.assertEqual(self.main_tick(state, .84, 42), 2)
    self.assertEqual(self.main_tick(state, .92, 43), 0)
    self.assertEqual((state.frames, state.requests), (2, 1))
    self.assertFalse(state.pressing)

  def test_segment_5e9_transition_control_tick_pattern(self):
    # The last three SET frames at the persistent-loss transition were about
    # 0/20/30 ms, followed by release at the 60/80 ms control opportunities.
    state = PorterCruiseButtons()
    outputs = [self.speed_tick(state, t, i, target=67.7, current=75.)
               for i, t in enumerate((0., .02, .03, .06, .08))]
    self.assertEqual(outputs, [2, 2, None, 0, 0])

  def test_main_bunched_sample_is_not_made_up_at_release(self):
    state = self.ready_main()
    outputs = [self.main_tick(state, t, 40 + i)
               for i, t in enumerate((.80, .82, .83, .84, .86, .88, .90, .92))]
    self.assertEqual(outputs, [2, 2, None, 2, 2, 2, 0, None])
    self.assertEqual((state.frames, state.press_slots), (5, 6))

  def test_normal_19ms_samples_preserve_press_budgets(self):
    speed = PorterCruiseButtons()
    self.assertEqual([self.speed_tick(speed, i * .019, i) for i in range(5)],
                     [2, 2, 2, 0, 0])
    main = self.ready_main()
    self.assertEqual([self.main_tick(main, .80 + i * .019, 40 + i) for i in range(7)],
                     [2, 2, 2, 2, 2, 2, 0])

  def test_speed_release_on_ack_or_block_is_not_rate_limited(self):
    for override in (dict(current=49.), dict(blocked=True), dict(enabled=False)):
      with self.subTest(override=override):
        state = PorterCruiseButtons()
        self.assertEqual(self.speed_tick(state, 0., 0), 2)
        self.assertEqual(self.speed_tick(state, .01, 1, **override), 0)
    state = PorterCruiseButtons()
    self.assertEqual(self.speed_tick(state, 0., 0), 2)
    self.assertIsNone(self.speed_tick(state, .01, 1, manual=True))

  def test_main_release_and_driver_priority_are_not_rate_limited(self):
    for override in (dict(blocked=True), dict(request=False), dict(configured=False),
                     dict(gas_pressed=True), dict(stock_enabled=True)):
      with self.subTest(override=override):
        state = self.ready_main()
        self.assertEqual(self.main_tick(state, .80, 40), 2)
        self.assertEqual(self.main_tick(state, .81, 41, **override), 0)
        self.assertFalse(state.pressing)
    state = self.ready_main()
    self.assertEqual(self.main_tick(state, .80, 40), 2)
    self.assertIsNone(self.main_tick(state, .81, 41, manual_button=4))
    self.assertFalse(state.armed)

  def test_main_too_old_sample_does_not_wait_for_spacing(self):
    state = self.ready_main()
    self.assertEqual(self.main_tick(state, .80, 40), 2)
    self.assertIsNone(self.main_tick(state, .81, 41, sample_age_s=.009))
    self.assertIsNone(self.main_tick(state, .82, 41, sample_age_s=.019))
    self.assertEqual(state.frames, 1)

  def test_real_dispatch_time_preserves_20ms_despite_single_control_tick(self):
    speed = PorterCruiseButtons()
    self.assertEqual(self.speed_tick(speed, 0., 0, tx_now_s=100.), 2)
    self.assertEqual(self.speed_tick(speed, .01, 1, tx_now_s=100.020), 2)
    self.assertIsNone(self.speed_tick(speed, .02, 2, tx_now_s=100.030))
    self.assertEqual(self.speed_tick(speed, .03, 3, tx_now_s=100.040), 0)
    main = self.ready_main()
    self.assertEqual(self.main_tick(main, .80, 40, tx_now_s=100.), 2)
    self.assertEqual(self.main_tick(main, .81, 41, tx_now_s=100.020), 2)
    self.assertIsNone(self.main_tick(main, .82, 42, tx_now_s=100.030))
    self.assertEqual(self.main_tick(main, .84, 43, tx_now_s=100.040), 2)

  def test_invalid_dispatch_clock_cannot_send_positive_frames(self):
    for clock in (float('nan'), float('inf')):
      with self.subTest(clock=clock):
        self.assertIsNone(self.speed_tick(PorterCruiseButtons(), 0., 0, tx_now_s=clock))
        self.assertIsNone(self.main_tick(self.ready_main(), .80, 40, tx_now_s=clock))


if __name__ == '__main__':
  unittest.main()
