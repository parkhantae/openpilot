import unittest
from hyundai_porter_testlib import lib, packet, data, seed, init


class TestPorterMainSetSafety(unittest.TestCase):
  def prepare(self, param=9217):
    init(param)
    lib.set_timer(21000)
    seed(counter=1, main=True, speed=40)
    for counter in range(2, 35):
      lib.set_timer(21000 + (counter - 1) * 20000)
      seed(counter=counter, speed=40)

  def tx(self, button=2, counter=3):
    return lib.safety_tx_hook(packet(0x4f1, data(0x4f1, button=button, counter=counter)))

  def test_opt_in_and_physical_main_required(self):
    for param in (1025, 9217):
      init(param)
      seed(counter=1, speed=40)
      self.assertFalse(self.tx(counter=2))
    self.prepare(1025)
    self.assertFalse(self.tx())
    self.prepare()
    self.assertFalse(lib.get_controls_allowed())
    self.assertFalse(self.tx(button=1))
    self.assertTrue(self.tx())
    self.assertFalse(lib.get_controls_allowed())
    self.assertFalse(self.tx())  # cannot reuse the OEM sample

  def test_bounded_pulse_and_retry(self):
    self.prepare()
    self.assertTrue(self.tx())
    for i in range(3, 8):
      lib.set_timer(681000 + (i - 2) * 20000)
      seed(counter=i, speed=40)
      self.assertTrue(self.tx(counter=i + 1))
    lib.set_timer(801000)
    seed(counter=8, speed=40)
    self.assertFalse(self.tx(counter=9))
    self.assertTrue(self.tx(button=0))
    self.assertFalse(self.tx(counter=9))

  def test_overrides_and_state_guards(self):
    for changes in (dict(brake=True), dict(park=True), dict(hold=True), dict(drive=False), dict(gas=True),
                    dict(speed=29), dict(speed=161), dict(main=True), dict(button=4)):
      with self.subTest(changes=changes):
        self.prepare()
        lib.set_timer(701000)
        seed(counter=3, **(dict(speed=40) | changes))
        self.assertFalse(self.tx(counter=4))

  def test_stale_inputs_block(self):
    self.prepare()
    lib.set_timer(1000000)
    self.assertFalse(self.tx())

  def test_only_stock_feedback_enables_controls(self):
    self.prepare()
    self.assertTrue(self.tx())
    self.assertFalse(lib.get_controls_allowed())
    lib.set_timer(701000)
    seed(counter=3, speed=40, target=40)
    self.assertTrue(lib.get_controls_allowed())

  def test_cancel_and_brake_do_not_rearm_on_release(self):
    for change in (dict(button=4), dict(brake=True)):
      self.prepare()
      lib.set_timer(701000)
      seed(counter=3, speed=40, **change)
      lib.set_timer(721000)
      seed(counter=4, speed=40)
      self.assertFalse(self.tx(counter=5))

  def test_limiter_and_wrong_counter_cannot_start(self):
    self.prepare()
    self.assertFalse(self.tx(counter=4))
    limiter = (1 << 13).to_bytes(8, 'little')
    self.assertTrue(lib.safety_rx_hook(packet(0x371, limiter)))
    self.assertFalse(self.tx())

  def test_main_press_must_be_confirmed_for_half_second(self):
    init(9217)
    lib.set_timer(21000)
    seed(counter=1, main=True, speed=40)
    lib.set_timer(41000)
    seed(counter=2, speed=40)
    self.assertFalse(self.tx())

  def test_log544_manual_engagement_syncs_main_parity(self):
    init(9217)
    lib.set_timer(21000)
    seed(counter=1, button=2, speed=40)
    lib.set_timer(41000)
    seed(counter=2, target=40, speed=40)
    lib.set_timer(61000)
    seed(counter=3, target=40, main=True, speed=40)  # MAIN OFF, feedback still ON
    lib.set_timer(81000)
    seed(counter=4, speed=40)
    self.assertFalse(self.tx(counter=5))
    lib.set_timer(101000)
    seed(counter=5, main=True, speed=40)  # MAIN ON again
    for counter in range(6, 34):
      lib.set_timer(101000 + (counter - 5) * 20000)
      seed(counter=counter, speed=40)
    self.assertTrue(self.tx(counter=34))

  def test_feedback_does_not_rearm_after_cancel(self):
    self.prepare()
    lib.set_timer(701000)
    seed(counter=3, speed=40, button=4)
    lib.set_timer(721000)
    seed(counter=4, speed=40, target=40)
    lib.set_timer(801000)
    seed(counter=8, speed=40)
    self.assertFalse(self.tx(counter=9))

  def test_bounded_cancel_release_uses_existing_native_permission(self):
    from opendbc.car.hyundai.porter_cancel import PorterCancelButtons
    from hyundai_porter_testlib import engage
    engage()
    pulse = PorterCancelButtons()
    emitted = []
    for tick in range(150):
      lib.set_timer(13000 + tick * 10000)
      counter = tick // 2 + 3
      if tick % 2 == 0:
        seed(counter=counter, target=42, speed=40)
      button = pulse.update(tick * .01, counter, requested=True, stock_enabled=True, preferred_delay=.01)
      if button is not None:
        emitted.append(button)
        self.assertTrue(lib.safety_tx_hook(packet(0x4f1, data(0x4f1, button=button, counter=counter+1))))
    self.assertIn(4, emitted)
    self.assertIn(0, emitted)
    self.assertNotIn(1, emitted)
    self.assertNotIn(2, emitted)

  def test_new_acceleration_release_rearms_after_override_only_with_main(self):
    for override, expected in ((dict(brake=True), True), (dict(button=4), True), (dict(main=True), False)):
      self.prepare()
      lib.set_timer(701000)
      seed(counter=3, speed=40, **override)
      lib.set_timer(721000)
      seed(counter=4, speed=40)
      self.assertFalse(self.tx(counter=5))
      for i in range(5, 16):
        lib.set_timer(721000+(i-4)*20000)
        seed(counter=i, speed=40, gas=i<15)
      self.assertEqual(self.tx(counter=16), expected)

  def test_gas_held_through_override_does_not_rearm(self):
    self.prepare()
    lib.set_timer(701000)
    seed(counter=3, speed=40, gas=True, brake=True)
    for i in range(4, 16):
      lib.set_timer(701000+(i-3)*20000)
      seed(counter=i, speed=40, gas=i<15)
    self.assertFalse(self.tx(counter=16))

  def test_startup_set_duration_bound_independent_of_frame_count(self):
    self.prepare()
    self.assertTrue(self.tx())
    for i in range(3, 9):
      lib.set_timer(681000+(i-2)*20000)
      seed(counter=i, speed=40)
    self.assertFalse(self.tx(counter=9))  # 120ms elapsed, only one frame sent

  def test_seventh_startup_set_frame_is_blocked_before_time_limit(self):
    self.prepare()
    self.assertTrue(self.tx())
    for i in range(3, 8):
      lib.set_timer(681000+(i-2)*10000)
      seed(counter=i, speed=40)
      self.assertTrue(self.tx(counter=i+1))
    lib.set_timer(741000)
    seed(counter=8, speed=40)
    self.assertFalse(self.tx(counter=9))

  def test_initial_on_seed_never_authorizes_transmission_or_pedal_rearm(self):
    init(25601)
    for counter in range(1, 40):
      lib.set_timer(1000+counter*20000)
      seed(counter=counter, speed=40, gas=counter<25)
      self.assertFalse(self.tx(counter=counter+1))
    self.assertFalse(lib.get_controls_allowed())

  def test_initial_on_two_main_presses_preserve_correct_native_parity(self):
    init(25601)
    lib.set_timer(21000)
    seed(counter=1, main=True, speed=40)
    lib.set_timer(41000)
    seed(counter=2, speed=40)
    self.assertFalse(self.tx())
    lib.set_timer(61000)
    seed(counter=3, main=True, speed=40)
    for counter in range(4, 36):
      lib.set_timer(61000+(counter-3)*20000)
      seed(counter=counter, speed=40)
    self.assertTrue(self.tx(counter=36))
    self.assertFalse(lib.get_controls_allowed())

  def test_startup_timing_trial_and_feedback_learning_pass_native(self):
    from opendbc.car.hyundai.porter_main_set import PorterMainSet
    init(9217)
    pulse=PorterMainSet()
    starts=[]
    for tick in range(180):
      lib.set_timer(21000+tick*10000)
      counter=tick//2
      stock=tick>=168
      if tick % 2==0:
        seed(counter=counter,main=tick==0,target=40 if stock else 0,speed=40)
      was=pulse.pressing
      b=pulse.update(tick*.01,counter,main_pressed=tick<2,manual_button=0,blocked=False,
                     request=True,stock_enabled=stock,configured=True)
      if b is not None:
        self.assertTrue(lib.safety_tx_hook(packet(0x4f1,data(0x4f1,button=b,counter=counter+1))),(tick,b))
        if b==2 and not was:
          starts.append(tick)
    self.assertEqual(starts,[52,163])
    self.assertEqual(pulse.preferred_delay,.01)
