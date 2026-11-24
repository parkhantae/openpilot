"""Current MAIN-settling cue exception against the real native safety hooks."""
import unittest

from hyundai_porter_testlib import data, init, lib, packet, seed
from opendbc.car.hyundai.porter_main_set import PorterMainSet


class TestPorterMainSettlingSafety(unittest.TestCase):
  TX_MSGS = [[0x340, 0], [0x4F1, 0], [0x485, 0]]

  def feed(self, tick, *, offset=21000, **change):
    lib.set_timer((offset + tick * 10000) & 0xFFFFFFFF)
    if tick % 2 == 0:
      values = dict(speed=40, target=0, gas=10 <= tick < 47, main=20 <= tick < 34)
      values.update(change)
      seed(counter=tick // 2, **values)

  def tx(self, tick):
    return lib.safety_tx_hook(packet(0x4f1, data(0x4f1, button=2, counter=tick // 2 + 1)))

  def test_real_host_waits_for_main_then_one_bounded_press_passes_native(self):
    for offset in (21000, (1 << 32) - 400000):
      init(15489)
      host = PorterMainSet(two_press=True, single_press=True, long_press=True)
      frames = []
      for tick in range(150):
        self.feed(tick, offset=offset)
        value = host.update(tick * .01, tick // 2, main_pressed=20 <= tick < 34,
                            manual_button=0, blocked=False, request=tick >= 47,
                            stock_enabled=False, configured=True, gas_pressed=10 <= tick < 47,
                            sample_age_s=.004)
        if value is not None:
          self.assertTrue(lib.safety_tx_hook(packet(0x4f1, data(0x4f1, button=value, counter=tick // 2 + 1))),
                          (offset, tick, value))
          frames.append((tick, value))
        self.assertFalse(lib.get_controls_allowed())
      self.assertEqual(frames, [(t, 2) for t in range(70, 82, 2)] + [(82, 0)])

  def test_no_early_main_or_expired_cue_and_old_profile_is_unchanged(self):
    for profile in (15489, 15361):
      init(profile)
      for tick in range(83):
        self.feed(tick)
        if tick == 68:
          self.assertFalse(self.tx(tick))  # MAIN has not settled.
        if tick == 82:
          self.assertFalse(self.tx(tick))  # Original release cannot be replayed.
      init(profile)
      for tick in range(71):
        self.feed(tick)
      self.assertEqual(self.tx(70), profile == 15489)

  def test_override_during_main_wait_revokes_cue_without_later_replay(self):
    for change in ({'brake': True}, {'gas': True}, {'button': 4}, {'main': True},
                   {'drive': False}, {'hold': True}, {'park': True}, {'speed': 20}):
      init(15489)
      for tick in range(71):
        self.feed(tick, **(change if 54 <= tick < 60 else {}))
      self.assertFalse(self.tx(70), change)

  def test_restored_speed_without_an_eligible_pedal_release_cannot_start(self):
    init(15489)
    for tick in range(71):
      self.feed(tick, **({'speed': 20} if 46 <= tick < 52 else {}))
    self.assertFalse(self.tx(70))

  def test_main_wait_cannot_queue_a_release_from_inside_retry_quiet_period(self):
    init(15489)
    for tick in range(411):
      self.feed(tick, gas=20 <= tick < 100 or 340 <= tick < 390,
                main=tick in (0, 300, 360))
      if tick == 100:
        self.assertTrue(self.tx(tick))
      if tick == 102:
        self.assertTrue(lib.safety_tx_hook(packet(0x4f1, data(0x4f1, button=0, counter=tick // 2 + 1))))
    # The release was before last TX+3s. Even though that wait and MAIN
    # settling have now finished, it cannot become a new automatic SET.
    self.assertFalse(self.tx(410))
