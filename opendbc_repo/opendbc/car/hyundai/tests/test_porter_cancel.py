import ast
from pathlib import Path
from types import SimpleNamespace as NS
import unittest

from opendbc.car.hyundai.porter_cancel import PorterLowSpeedCancel, porter_cancel_target


class TestPorterCancelTarget(unittest.TestCase):
  def target(self, planner=50, selected=60, navigation=None, ego=10, distance=100, relative=0, visible=False):
    return porter_cancel_target(planner, selected, navigation, ego, distance, relative, 2, lead_visible=visible)

  def test_raw_stop_navigation_and_selected_targets(self):
    self.assertEqual(self.target(planner=0), 0)
    self.assertEqual(self.target(navigation=20), 20)
    self.assertEqual(self.target(selected=25), 25)
    self.assertEqual(self.target(navigation=0), 50)
    self.assertEqual(self.target(planner=None, selected=0, navigation=0), None)

  def test_only_existing_close_lead_constraint_can_supply_low_target(self):
    self.assertEqual(self.target(ego=10, distance=12, relative=-9, visible=True), 3.6)
    self.assertEqual(self.target(ego=10, distance=100, relative=-1, visible=True), 50)
    self.assertEqual(self.target(ego=5, distance=12, relative=1, visible=True), 50)
    self.assertEqual(self.target(ego=10, distance=12, relative=-9, visible=False), 50)

  def test_invalid_values_are_not_stop_requests(self):
    self.assertIsNone(self.target(planner=float('nan'), selected=-1, navigation=255))
    self.assertEqual(self.target(distance=float('nan'), visible=True), 50)


class TestPorterLowSpeedCancel(unittest.TestCase):
  def setUp(self):
    self.c = PorterLowSpeedCancel()

  def step(self, tick, target=20, eligible=True, enabled=True):
    return self.c.update(tick * .01, target, eligible=eligible, cruise_enabled=enabled)

  def test_continuous_confirmation_latches_until_oem_off_then_rearms(self):
    for tick in range(30):
      self.assertFalse(self.step(tick))
    self.assertTrue(self.step(30))
    self.assertTrue(self.step(31, 50))
    self.assertFalse(self.step(32, enabled=False))
    for tick in range(33, 63):
      self.assertFalse(self.step(tick))
    self.assertTrue(self.step(63))

  def test_disabled_and_thirty_encoding_never_cancel(self):
    for tick in range(100):
      self.assertFalse(self.step(tick, eligible=False))
    for tick in range(100, 200):
      self.assertFalse(self.step(tick, target=8.333333015441895 * 3.6))

  def test_target_recovery_invalid_and_observation_gap_restart_confirmation(self):
    for tick in range(20):
      self.step(tick)
    self.assertFalse(self.step(20, 30))
    for tick in range(21, 51):
      self.assertFalse(self.step(tick))
    self.assertFalse(self.step(61))
    for tick in range(62, 92):
      self.assertFalse(self.step(tick))
    self.assertTrue(self.step(92))
    self.assertFalse(self.step(93, eligible=False))
    self.assertFalse(self.step(94, target=float('nan')))


class TestPorterCancelPublish(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    root = Path(__file__).resolve().parents[5]
    tree = ast.parse((root / 'openpilot/selfdrive/controls/controlsd.py').read_text())
    fn = next(n for c in tree.body if isinstance(c, ast.ClassDef) and c.name == 'Controls'
              for n in c.body if isinstance(n, ast.FunctionDef) and n.name == 'update_porter_cancel')
    env = dict(PorterLowSpeedCancel=PorterLowSpeedCancel, porter_cancel_target=porter_cancel_target,
               DT_CTRL=.01, cloudlog=NS(info=lambda *args: None))
    exec(compile(ast.Module(body=[fn], type_ignores=[]), 'actual_porter_cancel_adapter', 'exec'), env)
    cls.function = staticmethod(env['update_porter_cancel'])

  def setUp(self):
    class SM(dict):
      frame = 0

      def all_checks(self, services):
        return all(service not in self.invalid for service in services)
    self.sm = SM(radarState=NS(leadOne=NS(status=False, dRel=0, vRel=0)),
                 selfdriveState=NS(personality=NS(raw=1)))
    self.sm.invalid = set()
    self.values = dict(PorterAutoCancelBelow30=False, SpeedFromPCM=0)
    self.obj = NS(CP=NS(brand='hyundai', carFingerprint='HYUNDAI_PORTER_II_EV',
                       pcmCruise=True, openpilotLongitudinalControl=False),
                  params=NS(get_bool=lambda k: self.values[k], get_int=lambda k: self.values[k]),
                  sm=self.sm, porter_low_speed_cancel=PorterLowSpeedCancel())
    self.cs = NS(canValid=True, accFaulted=False, vCruiseCluster=50, vEgo=10,
                 cruiseState=NS(enabled=True))
    self.cc = NS(enabled=True, cruiseControl=NS(cancel=False, resume=True))

  def run_frames(self, planner=20, nav=None, start=0):
    for tick in range(start, start + 40):
      self.sm.frame = tick
      self.function(self.obj, self.cs, self.cc, planner, nav)

  def test_off_leaves_existing_controls_and_cancellation_unchanged(self):
    self.run_frames(planner=0)
    self.assertFalse(self.cc.cruiseControl.cancel)
    self.assertTrue(self.cc.cruiseControl.resume)
    self.cc.cruiseControl.cancel = True
    self.run_frames()
    self.assertTrue(self.cc.cruiseControl.cancel)

  def test_on_changes_only_cancel_resume_and_can_be_disabled_live(self):
    self.values['PorterAutoCancelBelow30'] = True
    self.run_frames()
    self.assertTrue(self.cc.cruiseControl.cancel)
    self.assertFalse(self.cc.cruiseControl.resume)
    self.values['PorterAutoCancelBelow30'] = False
    self.cc.cruiseControl.cancel, self.cc.cruiseControl.resume = False, True
    self.run_frames(start=40)
    self.assertFalse(self.cc.cruiseControl.cancel)
    self.assertTrue(self.cc.cruiseControl.resume)

  def test_stale_plan_and_other_vehicles_or_modes_do_not_trigger(self):
    self.values['PorterAutoCancelBelow30'] = True
    self.sm.invalid.add('longitudinalPlan')
    self.run_frames(planner=0)
    self.assertFalse(self.cc.cruiseControl.cancel)
    self.sm.invalid.clear()
    self.obj.CP.carFingerprint = 'OTHER'
    self.run_frames(start=40)
    self.assertFalse(self.cc.cruiseControl.cancel)
    self.obj.CP.carFingerprint = 'HYUNDAI_PORTER_II_EV'
    self.values['SpeedFromPCM'] = 1
    self.run_frames(start=80)
    self.assertFalse(self.cc.cruiseControl.cancel)

  def test_low_vehicle_speed_alone_is_not_cancellation(self):
    self.values['PorterAutoCancelBelow30'] = True
    self.cs.vEgo = 2
    self.run_frames(planner=50)
    self.assertFalse(self.cc.cruiseControl.cancel)
