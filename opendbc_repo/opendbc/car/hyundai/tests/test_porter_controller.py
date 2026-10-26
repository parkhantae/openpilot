import ast
import math
from pathlib import Path
from types import SimpleNamespace as NS
import unittest


class TestPorterButtonGate(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    tree = ast.parse((Path(__file__).resolve().parents[1] / "carcontroller.py").read_text(encoding="utf-8"))
    function = next(n for c in tree.body if isinstance(c, ast.ClassDef) and c.name == "CarController"
                    for n in c.body if isinstance(n, ast.FunctionDef) and n.name == "make_spam_button")
    env = {"np": NS(isfinite=math.isfinite), "CAR": NS(HYUNDAI_PORTER_II_EV="porter"),
           "Buttons": NS(NONE=0, RES_ACCEL=1, SET_DECEL=2),
           "structs": NS(CarState=NS(GearShifter=NS(drive="drive"))),
           "CV": NS(MS_TO_KPH=3.6, MS_TO_MPH=2.2369362920544)}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "actual_make_spam_button", "exec"), env)
    cls.function = staticmethod(env["make_spam_button"])

  def setUp(self):
    self.controller = NS(CP=NS(carFingerprint="porter"), frame=100, last_button_frame=0,
                         activateCruise=0, button_spamming_count=0, button_wait=12,
                         button_spam1=8, button_spam2=30, speed_from_pcm=0, prev_clu_speed=50)
    self.cc = NS(enabled=True, cruiseControl=NS(cancel=False, resume=False),
                 hudControl=NS(setSpeed=51/3.6, leadVisible=True))
    self.cs = NS(is_metric=True, cruise_buttons=[0], main_buttons=[0],
                 out=NS(cruiseState=NS(enabled=True, speed=50/3.6), canValid=True,
                        accFaulted=False, gasPressed=False, standstill=False,
                        gearShifter="drive", brakePressed=False, brakeHoldActive=False,
                        parkingBrake=False, vEgo=50/3.6, activateCruise=1))

  def test_existing_speed_adjustment_is_connected(self):
    self.assertEqual(self.function(self.controller, self.cc, self.cs), 1)
    self.setUp()
    self.cc.hudControl.setSpeed = 49/3.6
    self.assertEqual(self.function(self.controller, self.cc, self.cs), 2)

  def test_disabled_stock_cruise_and_auto_activation_blocked(self):
    self.cs.out.cruiseState.enabled = False
    self.assertEqual(self.function(self.controller, self.cc, self.cs), 0)
    self.setUp()
    self.cc.enabled = False
    self.assertEqual(self.function(self.controller, self.cc, self.cs), 0)

  def test_each_pedal_state_fault_and_gear_blocks(self):
    for field, value in (("canValid", False), ("accFaulted", True), ("gasPressed", True),
                         ("standstill", True), ("gearShifter", "reverse"), ("brakePressed", True),
                         ("brakeHoldActive", True), ("parkingBrake", True)):
      self.setUp()
      setattr(self.cs.out, field, value)
      self.assertEqual(self.function(self.controller, self.cc, self.cs), 0, field)

  def test_cancel_resume_and_manual_buttons_take_priority(self):
    for field in ("cancel", "resume"):
      self.setUp()
      setattr(self.cc.cruiseControl, field, True)
      self.assertEqual(self.function(self.controller, self.cc, self.cs), 0)
    for field in ("cruise_buttons", "main_buttons"):
      self.setUp()
      setattr(self.cs, field, [1])
      self.assertEqual(self.function(self.controller, self.cc, self.cs), 0)

  def test_invalid_target_and_other_car_scope(self):
    self.cc.hudControl.setSpeed = float("nan")
    self.assertEqual(self.function(self.controller, self.cc, self.cs), 0)
    self.setUp()
    self.controller.CP.carFingerprint = "other"
    self.assertEqual(self.function(self.controller, self.cc, self.cs), 1)


if __name__ == "__main__":
  unittest.main()
