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
    self.assertEqual(porter.porter_lead_target_kph(80, 20, 70, -5, 1), 80)
    self.assertEqual(porter.porter_lead_target_kph(80, 20, 70, -5, 4), 54)

  def test_longer_coasting_horizon_starts_reduction_earlier(self):
    self.assertEqual(porter.porter_lead_target_kph(80, 10, 40, -5, 2), 30)

  def test_close_same_speed_lead_prevents_further_acceleration(self):
    self.assertEqual(porter.porter_lead_target_kph(80, 20, 20, 0, 2), 72)

  def test_opening_distant_or_absent_lead_does_not_change_target(self):
    self.assertEqual(porter.porter_lead_target_kph(80, 20, 15, 1, 4), 80)
    self.assertEqual(porter.porter_lead_target_kph(80, 20, 100, -1, 4), 80)
    self.assertEqual(porter.porter_lead_target_kph(80, 20, 15, -5, 4, lead_visible=False), 80)

  def test_stopped_lead_target_respects_porter_floor(self):
    self.assertEqual(porter.porter_lead_target_kph(50, 15, 12, -15, 4), porter.PORTER_CRUISE_MIN_KPH)


class TestPorterLeadTracker(unittest.TestCase):
  def setUp(self):
    self.tracker = porter.PorterLeadTracker()

  def update(self, now, *, target=80, stock=50, ego=10, distance=40, relative=-5, visible=True, gap=2):
    return self.tracker.update(now, target, stock, ego, distance, relative, gap, lead_visible=visible)

  def test_distant_lead_allows_target_recovery_without_opening_confirmation(self):
    self.assertEqual(self.update(0, target=60, stock=42, distance=100, relative=-1), 60)
    self.assertEqual(self.update(.1, target=60, stock=42, distance=100, relative=.1), 60)

  def test_close_opening_lead_still_requires_confirmation(self):
    self.assertEqual(self.update(0, target=60, stock=30, distance=15, relative=1), 30)
    self.assertEqual(self.update(.49, target=60, stock=30, distance=15, relative=1), 30)
    self.assertEqual(self.update(.5, target=60, stock=30, distance=15, relative=1), 60)

  def test_brief_opening_blip_does_not_restore_memorized_speed(self):
    self.assertEqual(self.update(0, target=60, stock=30, distance=15, relative=-1), 30)
    self.assertEqual(self.update(.1, target=60, stock=30, distance=15, relative=1), 30)
    self.assertEqual(self.update(.2, target=60, stock=30, distance=15, relative=-1), 30)

  def test_short_dropout_keeps_conservative_cap(self):
    self.assertEqual(self.update(0), 30)
    self.assertEqual(self.update(.5, visible=False), 30)

  def test_brief_closing_projection_noise_keeps_deceleration_target(self):
    # Recorded pattern: a closing lead requests ~53 km/h, then a small
    # relative-speed change puts the projection outside the selected gap.
    cap = self.update(0, target=80, stock=71, ego=19, distance=56, relative=-4)
    self.assertAlmostEqual(cap, 54)
    self.assertEqual(self.update(.05, target=80, stock=70, ego=19, distance=56, relative=-1), cap)
    self.assertEqual(self.update(.3, target=80, stock=70, ego=19, distance=56, relative=-1), cap)
    self.assertEqual(self.update(.61, target=80, stock=70, ego=19, distance=56, relative=-1), 80)

  def test_deceleration_hold_expires_even_with_continuous_lead_samples(self):
    self.update(0, target=80, stock=71, ego=19, distance=56, relative=-4)
    for i in range(1, 61):
      self.update(i * .01, target=80, stock=70, ego=19, distance=56, relative=-1)
    self.assertEqual(self.update(.61, target=80, stock=70, ego=19, distance=56, relative=-1), 80)

  def test_new_closing_constraint_refreshes_cap_but_lower_target_wins(self):
    self.update(0, target=80, stock=71, ego=19, distance=56, relative=-4)
    self.assertAlmostEqual(self.update(.1, target=80, stock=70, ego=19, distance=40, relative=-3), 57.6)
    self.assertEqual(self.update(.2, target=45, stock=70, ego=19, distance=56, relative=-1), 45)

  def test_expired_observation_gap_does_not_restore_an_old_deceleration_cap(self):
    self.update(0, target=80, stock=71, ego=19, distance=56, relative=-4)
    self.assertEqual(self.update(2, target=80, stock=70, ego=19, distance=56, relative=-1), 80)

  def test_log55a_overspeed_recovery_before_vehicle_reaches_stock_setting(self):
    # Segment46: the display is still near68.25, while stock was lowered to63.
    # The lead is beyond the configured projected gap; noisy vRel near zero
    # must not pin the recovered planner target67–69 to the old stock63.
    for t,relative in ((0,-.082),(.1,.1),(.2,-.259)):
      target=self.tracker.update(t,68.3,63,63.6/3.6,44.22,relative,3,gap_time_s=2.,reaction_s=6.)
      self.assertEqual(target,68.3)

  def test_recovery_keeps_closing_constraint_and_lower_planner_target(self):
    self.assertEqual(self.update(0,target=80,stock=70,ego=19,distance=40,relative=-3),57.6)
    self.assertEqual(self.update(.7,target=45,stock=70,ego=19,distance=100,relative=-1),45)

  def test_recovery_does_not_use_dropout_as_clearance(self):
    self.assertEqual(self.update(0,target=60,stock=42,distance=100,relative=-1),60)
    self.assertEqual(self.update(.1,target=60,stock=42,visible=False),42)

  def test_invalid_plan_or_radar_cannot_raise_target_but_lower_target_remains(self):
    for visible in (False,True):
      self.assertEqual(self.tracker.update(0,80,60,10,100,1,2,lead_visible=visible,recovery_allowed=False),60)
      self.assertEqual(self.tracker.update(.1,45,60,10,100,1,2,lead_visible=visible,recovery_allowed=False),45)

  def test_malformed_visible_lead_does_not_grant_clear_road_recovery(self):
    for ego,distance,relative,visible in ((10,float('nan'),0,True),(10,0,0,True),
                                          (10,100,float('nan'),True),(float('nan'),0,0,False)):
      tracker=porter.PorterLeadTracker()
      self.assertEqual(tracker.update(0,80,60,ego,distance,relative,2,lead_visible=visible),60)
      self.assertFalse(tracker.recovery_ready)

  def test_held_lead_target_allows_next_acknowledged_deceleration_step(self):
    pulse = porter.PorterCruiseButtons()

    def step(now, stock, relative):
      target = self.update(now, target=80, stock=stock, ego=19, distance=56, relative=relative)
      return pulse.update(now, target, stock, now, enabled=True)
    self.assertEqual(step(0, 71, -4), 2)
    self.assertEqual(step(.04, 70, -1), 0)
    self.assertEqual(step(.06, 70, -1), 0)
    self.assertEqual(step(.32, 70, -1), 2)
    self.assertEqual((pulse.requests, pulse.acks), (2, 1))

  def test_confirmed_opening_lead_clears_deceleration_hold(self):
    self.update(0, target=80, stock=71, ego=19, distance=56, relative=-4)
    self.update(.05, target=80, stock=70, ego=19, distance=56, relative=5)
    self.assertEqual(self.update(.56, target=80, stock=70, ego=19, distance=56, relative=5), 80)

  def test_expired_dropout_releases_cap(self):
    self.assertEqual(self.update(0), 30)
    self.assertEqual(self.update(.3, visible=False), 30)
    self.assertEqual(self.update(.59, visible=False), 30)
    self.assertEqual(self.update(.61, visible=False), 80)

  def test_invalid_or_reversed_time_does_not_reuse_lead(self):
    self.assertEqual(self.update(1), 30)
    self.assertEqual(self.update(.9, visible=False), 80)


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
