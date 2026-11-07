import unittest

from hyundai_porter_testlib import init, lib, seed, data, packet
import test_hyundai_porter_set_pair as pair_driver
from opendbc.car.hyundai.porter_main_set import PorterMainSet


class TestPorterSingleLongSafety(unittest.TestCase):
  def test_real_host_streams_pass_native_including_early_on_and_timer_wrap(self):
    for offset in (21000, (1 << 32) - 1_100_000):
      for on in (None, 103):
        init(15489)
        pulse = PorterMainSet(two_press=True, single_press=True, long_press=True)
        starts = []
        frames = []
        for tick in range(900):
          gas = 20 <= tick < 100 or 420 <= tick < 450 or 800 <= tick < 820
          stock = on is not None and on <= tick < 380
          lib.set_timer((offset + tick * 10000) & 0xFFFFFFFF)
          if tick % 2 == 0:
            seed(counter=tick // 2, speed=40, gas=gas, main=tick == 0, target=40 if stock else 0)
          before = pulse.requests
          button = pulse.update(
            tick * 0.01,
            tick // 2,
            main_pressed=tick < 2,
            manual_button=0,
            blocked=False,
            request=not gas,
            stock_enabled=stock,
            configured=True,
            gas_pressed=gas,
          )
          if pulse.requests != before:
            starts.append(tick)
          if button is not None:
            self.assertTrue(lib.safety_tx_hook(packet(0x4F1, data(0x4F1, button=button, counter=tick // 2 + 1))), (offset, on, tick, button))
            frames.append(button)
        self.assertEqual(starts, [100, 450, 820])
        self.assertEqual(frames.count(0), 3)
        self.assertEqual(frames.count(2), 18 if on is None else 14)

  def test_seventh_frame_and_second_press_are_rejected(self):
    driver = pair_driver.TestPorterPairSafety()
    driver.prime(profile=15489)
    for t in range(100, 112, 2):
      self.assertTrue(driver.tx(t))
    self.assertFalse(driver.tx(112))
    driver.prime(profile=15489)
    for t in range(100, 112, 2):
      self.assertTrue(driver.tx(t))
    self.assertTrue(driver.tx(112, button=0))
    self.assertFalse(driver.tx(120))
    self.assertFalse(driver.tx(420))  # No new pedal cue.

  def test_elapsed_limit_is_independent_of_frame_count(self):
    driver = pair_driver.TestPorterPairSafety()
    driver.prime(profile=15489)
    self.assertTrue(driver.tx(100))
    self.assertFalse(driver.tx(112))

  def test_overrides_abort_long_press(self):
    for change in ({"brake": True}, {"gas": True}, {"main": True}, {"button": 4}, {"drive": False}, {"hold": True}, {"park": True}):
      driver = pair_driver.TestPorterPairSafety()
      driver.prime(profile=15489)
      self.assertTrue(driver.tx(100))
      driver.advance(102, **change)
      self.assertFalse(driver.tx(104), change)

  def test_profile_cannot_mix_with_other_control_flags(self):
    for flag in (2, 4, 8, 16, 32, 64, 256, 512, 16384, 32768):
      lib.set_safety_hooks(8, 15489 | flag)
      lib.init_tests()
      self.assertFalse(lib.safety_config_valid(), flag)

  def test_switching_back_retains_legacy_short_press_limit(self):
    for profile in (15489, 15361, 15489):
      driver = pair_driver.TestPorterPairSafety()
      driver.prime(profile=profile)
      for t in (100, 102, 104):
        self.assertTrue(driver.tx(t))
      self.assertEqual(driver.tx(106), profile == 15489)
