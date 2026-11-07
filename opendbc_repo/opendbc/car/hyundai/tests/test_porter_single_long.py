import unittest
from types import SimpleNamespace as NS

from opendbc.car.hyundai.porter_main_set import PorterMainSet
from opendbc.car.hyundai.porter import porter_auto_set_speed_valid


class TestPorterSingleLong(unittest.TestCase):
  def test_six_frame_single_press_matches_4757_timing(self):
    state = PorterMainSet(two_press=True, single_press=True, long_press=True)
    outputs = []
    for tick in range(900):
      gas = 20 <= tick < 100 or 420 <= tick < 450
      button = state.update(
        tick * 0.01, tick // 2, main_pressed=tick < 2, manual_button=0, blocked=False, request=not gas, stock_enabled=False, configured=True, gas_pressed=gas
      )
      if button is not None:
        outputs.append((tick, button))
    expected = []
    for start in (100, 450):
      expected.extend((start + dt, 2) for dt in (0, 2, 4, 6, 8, 10))
      expected.append((start + 12, 0))
    self.assertEqual(outputs, expected)
    self.assertEqual(state.requests, 2)
    self.assertEqual(state.pair_remaining, 0)

  def test_new_profile_keeps_both_wheels_at_thirty(self):
    cp = NS(safetyConfigs=[NS(safetyParam=15489)])
    cs = NS(vEgo=29 / 3.6, vEgoCluster=32 / 3.6, wheelSpeeds=NS(fl=29 / 3.6, rr=30 / 3.6))
    self.assertFalse(porter_auto_set_speed_valid(cp, cs))
    cs.wheelSpeeds.fl = 30 / 3.6
    self.assertTrue(porter_auto_set_speed_valid(cp, cs))

  def test_late_samples_cannot_extend_a_started_long_press(self):
    state = PorterMainSet(two_press=True, single_press=True, long_press=True)
    outputs = []
    for tick in range(200):
      gas = 20 <= tick < 100
      button = state.update(
        tick * 0.01,
        tick // 2,
        main_pressed=tick < 2,
        manual_button=0,
        blocked=False,
        request=not gas,
        stock_enabled=False,
        configured=True,
        gas_pressed=gas,
        sample_age_s=0.004 if tick <= 100 else 0.012,
      )
      if button is not None:
        outputs.append((tick, button))
    self.assertEqual(outputs, [(100, 2), (112, 0)])
