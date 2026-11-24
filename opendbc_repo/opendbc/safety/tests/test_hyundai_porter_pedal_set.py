"""Actual active-cruise host output through unchanged production Panda hooks."""
import unittest

from hyundai_porter_testlib import data, init, lib, packet, seed
from opendbc.car.hyundai.porter_pedal_set import PorterPedalSet


class TestPorterPedalSetSafety(unittest.TestCase):
  TX_MSGS = [[0x340, 0], [0x4F1, 0], [0x485, 0]]

  def prime(self, profile):
    init(profile)
    lib.set_alternative_experience(1)  # Actual DisengageOnAccelerator=OFF configuration.
    lib.set_timer(2000)
    seed(counter=1, button=2, speed=58)
    lib.set_timer(3000)
    seed(counter=2, target=47, speed=58)
    self.assertTrue(lib.get_controls_allowed())

  def test_active_capture_one_press_has_no_additional_standby_authority(self):
    for profile in (1025, 15489):
      self.prime(profile)
      host = PorterPedalSet()
      outputs = []
      for tick in range(20):
        lib.set_timer(10000 + tick * 10000)
        seed(counter=tick + 3, target=47, gas=tick < 12, speed=58)
        value = host.update(1_000_000_000 + tick * 10_000_000,
                            1_120_000_000 if tick >= 12 else 0, 58 if tick >= 12 else 0, 47, tick // 2,
                            enabled=True, blocked=False, manual=False, gas=tick < 12, sample_age_s=0)
        if value is not None:
          self.assertTrue(lib.safety_tx_hook(packet(0x4f1, data(0x4f1, button=value, counter=tick + 4, speed=58))),
                          (profile, tick, value))
          outputs.append((tick, value))
      self.assertEqual(outputs, [(12, 2), (14, 2), (16, 2), (18, 0)])

  def test_native_still_blocks_gas_brake_fault_non_drive_and_invalid_messages(self):
    for profile in (1025, 15489):
      for change in ({'gas': True}, {'brake': True}, {'drive': False}, {'hold': True}, {'park': True}, {'target': 0}):
        self.prime(profile)
        lib.set_timer(20000)
        values = dict(target=47, counter=3, speed=58)
        values.update(change)
        seed(**values)
        self.assertFalse(lib.safety_tx_hook(packet(0x4f1, data(0x4f1, button=2, counter=4, speed=58))), (profile, change))
      self.prime(profile)
      self.assertFalse(lib.safety_tx_hook(packet(0x4f1, data(0x4f1, button=2, counter=3, main=True))))
      self.assertFalse(lib.safety_tx_hook(packet(0x4f1, data(0x4f1, button=2, counter=3), bus=1)))

  def test_release_does_not_restore_revoked_control_permission(self):
    for profile in (1025, 15489):
      self.prime(profile)
      lib.set_alternative_experience(0)  # Driver opted into disengagement on accelerator.
      lib.set_timer(20000)
      seed(target=47, speed=58, counter=3, gas=True)
      self.assertFalse(lib.get_controls_allowed())
      lib.set_timer(40000)
      seed(target=47, speed=58, counter=4, gas=False)
      self.assertFalse(lib.get_controls_allowed())
      self.assertFalse(lib.safety_tx_hook(packet(0x4f1, data(0x4f1, button=2, counter=5, speed=58))))
