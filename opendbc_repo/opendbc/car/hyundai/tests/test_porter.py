import importlib.util
import math
from pathlib import Path
from types import SimpleNamespace as NS
import unittest

spec = importlib.util.spec_from_file_location("porter_under_test", Path(__file__).resolve().parents[1] / "porter.py")
porter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(porter)


class TestPorterState(unittest.TestCase):
  def setUp(self):
    self.ret = NS(cruiseState=NS(), accFaulted=False, brakePressed=False)
    self.cp = NS(can_valid=True, _last_update_nanos=1_000_000_000,
                 ts_nanos={name: {"last": 990_000_000} for name in ("E_EMS11", "TCS13", "TCS15", "ELECT_GEAR")},
                 vl={"E_EMS11": {"Cruise_Limit_Target": 50},
                     "TCS13": {"DriverOverride": 0, "DriverBraking": 0, "PBRAKE_ACT": 0, "BrakeLight": 0, "ACCEnable": 0},
                     "TCS15": {"AVH_LAMP": 0}})

  def update(self, main=False, metric=True):
    porter.update_porter_state(self.ret, self.cp, main, metric)
    return self.ret.cruiseState

  def test_supported_speed_range_starts_at_confirmed_stock_floor(self):
    for target in range(porter.PORTER_CRUISE_MIN_KPH, 51):
      self.cp.vl["E_EMS11"]["Cruise_Limit_Target"] = target
      state = self.update()
      self.assertTrue(state.enabled)
      self.assertTrue(state.nonAdaptive)
      self.assertAlmostEqual(state.speed, target / 3.6)

  def test_zero_cancels(self):
    self.update()
    self.cp.vl["E_EMS11"]["Cruise_Limit_Target"] = 0
    state = self.update(main=True)
    self.assertTrue(state.available)
    self.assertFalse(state.enabled)
    self.assertEqual(state.speed, 0)

  def test_each_brake_source_blocks(self):
    for field, value in (("DriverOverride", 2), ("DriverBraking", 1), ("PBRAKE_ACT", 1)):
      self.setUp()
      self.cp.vl["TCS13"][field] = value
      self.assertFalse(self.update().enabled)
    self.setUp()
    self.cp.vl["TCS15"]["AVH_LAMP"] = 2
    self.assertFalse(self.update().enabled)

  def test_stale_missing_and_future(self):
    for name in self.cp.ts_nanos:
      for timestamp in (0, 1, 1_100_000_000):
        self.setUp()
        self.cp.ts_nanos[name]["last"] = timestamp
        self.assertFalse(self.update().enabled)
        self.assertTrue(self.ret.accFaulted)

  def test_invalid_target(self):
    for target in (-1, 1, 5, 29, 161, 255, float("nan"), float("inf")):
      self.setUp()
      self.cp.vl["E_EMS11"]["Cruise_Limit_Target"] = target
      self.assertFalse(self.update().enabled)
      self.assertTrue(self.ret.accFaulted)

  def test_invalid_can_fault_and_unsupported_units(self):
    self.cp.can_valid = False
    self.assertFalse(self.update().enabled)
    self.setUp()
    self.cp.vl["TCS13"]["ACCEnable"] = 1
    self.assertFalse(self.update().enabled)
    self.setUp()
    self.assertFalse(self.update(metric=False).enabled)

  def test_nonadaptive_exception_is_exact_configuration_only(self):
    cp = NS(brand="hyundai", carFingerprint="HYUNDAI_PORTER_II_EV", pcmCruise=True,
            openpilotLongitudinalControl=False, safetyConfigs=[NS(safetyModel="hyundai", safetyParam=1025)])
    self.assertTrue(porter.supports_porter_button_cruise(cp))
    for field, value in (("brand", "kia"), ("carFingerprint", "OTHER"),
                         ("pcmCruise", False), ("openpilotLongitudinalControl", True)):
      old = getattr(cp, field)
      setattr(cp, field, value)
      self.assertFalse(porter.supports_porter_button_cruise(cp))
      setattr(cp, field, old)
    cp.safetyConfigs[0].safetyParam = 1
    self.assertFalse(porter.supports_porter_button_cruise(cp))

  def test_pcm_cruise_minimum_matches_confirmed_stock_floor(self):
    cp = NS(brand="hyundai", carFingerprint="HYUNDAI_PORTER_II_EV")
    self.assertEqual(porter.pcm_cruise_min_kph(cp), 30)
    cp.carFingerprint = "OTHER"
    self.assertEqual(porter.pcm_cruise_min_kph(cp), 30)
    cp.carFingerprint = "HYUNDAI_PORTER_II_EV"
    cp.brand = "kia"
    self.assertEqual(porter.pcm_cruise_min_kph(cp), 30)


class TestPorterLeadTarget(unittest.TestCase):
  def test_close_closing_lead_caps_target_to_lead_speed(self):
    self.assertEqual(porter.porter_lead_target_kph(80, 20, 25, -5, 1), 54)

  def test_gap_level_changes_early_response_distance(self):
    self.assertEqual(porter.porter_lead_target_kph(80, 20, 35, -5, 1), 80)
    self.assertEqual(porter.porter_lead_target_kph(80, 20, 35, -5, 4), 54)

  def test_close_same_speed_lead_prevents_further_acceleration(self):
    self.assertEqual(porter.porter_lead_target_kph(80, 20, 20, 0, 2), 72)

  def test_opening_distant_or_absent_lead_does_not_change_target(self):
    self.assertEqual(porter.porter_lead_target_kph(80, 20, 15, 1, 4), 80)
    self.assertEqual(porter.porter_lead_target_kph(80, 20, 100, -1, 4), 80)
    self.assertEqual(porter.porter_lead_target_kph(80, 20, 15, -5, 4, lead_visible=False), 80)

  def test_stopped_lead_target_respects_porter_floor(self):
    self.assertEqual(porter.porter_lead_target_kph(50, 15, 12, -15, 4), porter.PORTER_CRUISE_MIN_KPH)


class TestPorterNaviTarget(unittest.TestCase):
  def test_navigation_profile_caps_higher_planner_target(self):
    self.assertEqual(porter.porter_navi_target_kph(65, 50), 50)

  def test_lower_planner_target_is_preserved(self):
    self.assertEqual(porter.porter_navi_target_kph(45, 50), 45)

  def test_below_stock_floor_clamps_to_30(self):
    self.assertEqual(porter.porter_navi_target_kph(35, 20), porter.PORTER_CRUISE_MIN_KPH)

  def test_invalid_navigation_target_does_not_override_planner(self):
    self.assertEqual(porter.porter_navi_target_kph(60, float("nan")), 60)
    self.assertTrue(math.isnan(porter.porter_navi_target_kph(float("nan"), 50)))


if __name__ == "__main__":
  unittest.main()
