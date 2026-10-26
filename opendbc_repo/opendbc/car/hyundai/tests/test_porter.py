import importlib.util
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

  def test_recorded_speed_range(self):
    for target in range(30, 51):
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
    for target in (-1, 1, 29, 161, 255, float("nan"), float("inf")):
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


if __name__ == "__main__":
  unittest.main()
