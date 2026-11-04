import unittest

from hyundai_porter_testlib import data, init, lib, packet, seed
from opendbc.car.hyundai.porter_main_set import PorterMainSet


class TestPorterPairSafety(unittest.TestCase):
  def prime(self, main=True, pedal=True, profile=15361, offset=21000):
    init(profile)
    self.offset = offset
    self.tick = 100
    self.raw = dict(speed=40, gas=False, main=False, target=0)
    for tick in range(101):
      lib.set_timer((self.offset + tick * 10000) & 0xFFFFFFFF)
      if tick % 2 == 0:
        seed(counter=tick // 2, speed=40, main=main and tick==0, gas=pedal and 20<=tick<100)

  def advance(self, tick, **changes):
    for current in range(self.tick + 1, tick + 1):
      if current == tick:
        self.raw.update(changes)
      lib.set_timer((self.offset + current * 10000) & 0xFFFFFFFF)
      if current % 2 == 0:
        seed(counter=current // 2, **self.raw)
    self.tick = tick

  def tx(self, tick, button=2, **changes):
    self.advance(tick, **changes)
    return lib.safety_tx_hook(packet(0x4f1, data(0x4f1, button=button, counter=tick // 2 + 1)))

  def first(self):
    for tick in (100, 102, 104):
      self.assertTrue(self.tx(tick))
    self.assertTrue(self.tx(106, button=0))

  def test_two_short_presses_pass_without_enabling_controls(self):
    self.prime()
    self.first()
    for tick in (114, 116, 118):
      self.assertTrue(self.tx(tick))
      self.assertFalse(lib.get_controls_allowed())
    self.assertTrue(self.tx(120, button=0))
    self.assertFalse(self.tx(128))

  def test_pair_across_native_microsecond_timer_wrap(self):
    self.prime(offset=(1 << 32) - 1_100_000)
    self.first()
    for tick in (114, 116, 118):
      self.assertTrue(self.tx(tick))
    self.assertTrue(self.tx(120, button=0))

  def test_pair_profile_cannot_mix_with_other_actuation_flags(self):
    for flag in (4, 8, 32, 256, 16384, 32768):
      lib.set_safety_hooks(8, 15361 | flag)
      lib.init_tests()
      self.assertFalse(lib.safety_config_valid(), flag)

  def test_legacy_profile_does_not_allow_rapid_second_press(self):
    self.prime(profile=11265)
    self.first()
    self.assertFalse(self.tx(114))

  def test_main_and_pedal_are_both_required(self):
    for main, pedal in ((False,True), (True,False)):
      self.prime(main=main, pedal=pedal)
      self.assertFalse(self.tx(100))

  def test_fourth_frame_without_release_aborts_the_pair(self):
    self.prime()
    for tick in (100, 102, 104):
      self.assertTrue(self.tx(tick))
    self.assertFalse(self.tx(106))
    self.assertTrue(self.tx(108, button=0))
    self.assertFalse(self.tx(116))

  def test_release_gap_cannot_be_skipped_or_renewed(self):
    self.prime()
    self.first()
    self.assertFalse(self.tx(110))
    self.assertTrue(self.tx(112, button=0))  # Does not renew the first release.
    self.assertTrue(self.tx(114))
    self.assertTrue(self.tx(116))
    self.assertTrue(self.tx(118))
    self.assertFalse(self.tx(120))

  def test_window_expiry_prevents_late_second_press(self):
    self.prime()
    self.first()
    self.assertTrue(self.tx(120, button=0))
    self.assertFalse(self.tx(126))

  def test_driver_and_vehicle_overrides_cancel_second(self):
    for change, restore in ((dict(brake=True),dict(brake=False)),
                            (dict(hold=True),dict(hold=False)),
                            (dict(park=True),dict(park=False)),
                            (dict(drive=False),dict(drive=True)),
                            (dict(gas=True),dict(gas=False)),
                            (dict(button=4),dict(button=0)),
                            (dict(button=1),dict(button=0)),
                            (dict(main=True),dict(main=False))):
      self.prime()
      self.first()
      self.advance(108, **change)
      self.advance(110, **restore)
      self.assertFalse(self.tx(114), change)

  def test_cancel_is_permitted_immediately_after_first_engagement(self):
    self.prime()
    self.first()
    self.advance(110, target=40)
    self.assertTrue(self.tx(112, button=4))
    self.assertFalse(self.tx(114))

  def test_stale_inputs_abort_pair_even_if_messages_later_recover(self):
    self.prime()
    self.first()
    lib.set_timer(21000 + 126 * 10000)
    self.assertFalse(lib.safety_tx_hook(packet(0x4f1, data(0x4f1, button=2, counter=54))))
    self.tick = 126
    self.assertFalse(self.tx(128))

  def test_stock_on_allows_only_the_bounded_second_press(self):
    self.prime()
    self.first()
    self.advance(110, target=40)
    self.assertTrue(lib.get_controls_allowed())
    self.assertTrue(self.tx(114))
    self.assertTrue(self.tx(116))
    self.assertTrue(self.tx(118))
    self.assertTrue(self.tx(120, button=0))
    self.assertFalse(self.tx(122))  # Not a third press through normal-step permission.
    self.assertTrue(self.tx(128))  # Ordinary engaged SET- remains available.

  def test_reused_counter_and_bad_parity_cannot_advance_release(self):
    self.prime()
    self.assertTrue(self.tx(100))
    self.assertFalse(lib.safety_tx_hook(packet(0x4f1, data(0x4f1, button=2, counter=51))))
    self.advance(102)
    self.assertFalse(lib.safety_tx_hook(packet(0x4f1, data(0x4f1, button=2, counter=53))))
    self.assertTrue(self.tx(102))
    self.assertTrue(self.tx(104))
    self.advance(106)
    invalid = bytearray(data(0x4f1, button=0, counter=54))
    invalid[0] ^= 32
    self.assertFalse(lib.safety_tx_hook(packet(0x4f1, invalid)))
    self.assertFalse(self.tx(114))

  def test_new_pair_needs_quiet_period_and_new_pedal_cycle(self):
    self.prime()
    self.first()
    for tick in (114,116,118):
      self.assertTrue(self.tx(tick))
    self.assertTrue(self.tx(120, button=0))
    self.advance(140, gas=True)
    self.assertFalse(self.tx(160, gas=False))  # Fresh cue cannot bypass 3s quiet.
    self.assertFalse(self.tx(420))  # That old cue expires, even after the wait.
    self.advance(430, gas=True)
    self.assertTrue(self.tx(450, gas=False))

  def test_real_host_pair_frames_pass_production_native_safety(self):
    for engage_at in (None,103,113):
      init(15361)
      pulse = PorterMainSet(two_press=True)
      starts = []
      for tick in range(500):
        stock = engage_at is not None and tick >= engage_at
        gas = 20 <= tick < 100
        lib.set_timer(21000 + tick * 10000)
        if tick % 2 == 0:
          seed(counter=tick // 2, speed=40, main=tick==0, gas=gas, target=40 if stock else 0)
        before = pulse.requests
        button = pulse.update(tick * .01, tick // 2, main_pressed=tick<2, manual_button=0,
                              blocked=False, request=not gas, stock_enabled=stock,
                              configured=True, gas_pressed=gas)
        if pulse.requests != before:
          starts.append(tick)
        if button is not None:
          self.assertTrue(lib.safety_tx_hook(packet(0x4f1, data(0x4f1, button=button, counter=tick // 2 + 1))),
                          (engage_at,tick,button))
      self.assertEqual(starts, [100,114])

  def test_real_host_retry_keeps_current_counter_without_delaying(self):
    init(15361)
    pulse = PorterMainSet(two_press=True)
    starts, outputs = [], []
    for tick in range(900):
      gas = 20 <= tick < 100 or 760 <= tick < 800
      lib.set_timer(21000 + tick * 10000)
      if tick % 2 == 0:
        seed(counter=tick // 2, speed=40, main=tick == 0, gas=gas)
      before = pulse.requests
      button = pulse.update(tick * .01, tick // 2, main_pressed=tick < 2, manual_button=0,
                            blocked=False, request=not gas, stock_enabled=False,
                            configured=True, gas_pressed=gas)
      if pulse.requests != before:
        starts.append(tick)
      if button is not None:
        outputs.append((tick, button))
        self.assertTrue(lib.safety_tx_hook(packet(0x4f1, data(0x4f1, button=button, counter=tick // 2 + 1))),
                        (tick, button))

    self.assertEqual(starts, [100,114,800,814])
    self.assertEqual(outputs[-8:], [(800,2),(802,2),(804,2),(806,0),
                                    (814,2),(816,2),(818,2),(820,0)])

  def test_host_pairs_with_can_poll_and_usb_latency_keep_current_native_counter(self):
    # A 50 Hz CLU11 arrives before the host's 100 Hz control tick. Transport
    # delay may let another OEM frame reach Panda before the queued command.
    # Exercise production host and native code in their actual event order.
    import heapq

    for poll_us, usb_us in ((4000, 0), (4000, 7000), (6000, 10000)):
      with self.subTest(poll_us=poll_us, usb_us=usb_us):
        init(15361)
        pulse = PorterMainSet(two_press=True)
        events, transmitted = [], []
        for tick in range(900):
          if tick % 2 == 0:
            heapq.heappush(events, (tick * 10000, 0, tick, None))
          heapq.heappush(events, (tick * 10000 + poll_us, 1, tick, None))
        while events:
          time_us, kind, tick, command = heapq.heappop(events)
          lib.set_timer(21000 + time_us)
          gas = 20 <= tick < 100 or 760 <= tick < 800
          if kind == 0:
            seed(counter=tick // 2, speed=40, main=tick == 0, gas=gas)
          elif kind == 1:
            button = pulse.update(tick * .01, tick // 2, main_pressed=tick < 2, manual_button=0,
                                  blocked=False, request=not gas, stock_enabled=False,
                                  configured=True, gas_pressed=gas,
                                  sample_age_s=(time_us - (tick // 2) * 20000) * 1e-6)
            if button is not None:
              heapq.heappush(events, (time_us + usb_us, 2, tick, button))
          else:
            self.assertTrue(lib.safety_tx_hook(packet(0x4f1, data(0x4f1, button=command,
                                                                 counter=tick // 2 + 1))),
                            (poll_us, usb_us, tick, command))
            transmitted.append(command)
        self.assertEqual(transmitted.count(2), 12)
        self.assertEqual(transmitted.count(0), 4)
        self.assertFalse(lib.get_controls_allowed())
