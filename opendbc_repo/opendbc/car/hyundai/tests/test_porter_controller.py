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


class TestPorterMessagePath(unittest.TestCase):
  def test_parameter_refresh_floors_porter_interval_only(self):
    from opendbc.car.hyundai.porter import porter_steer_request_frames

    tree = ast.parse((Path(__file__).resolve().parents[1] / "carcontroller.py").read_text(encoding="utf-8"))
    update = next(n for c in tree.body if isinstance(c, ast.ClassDef) and c.name == "CarController"
                  for n in c.body if isinstance(n, ast.FunctionDef) and n.name == "update")
    refresh = next(n for n in update.body if isinstance(n, ast.If) and ast.unparse(n.test) == "self.frame % 50 == 0")
    # Execute the actual periodic MaxAngleFrames read and its scoped guard.
    code = compile(ast.Module(body=refresh.body[:3], type_ignores=[]), "actual_angle_parameter_refresh", "exec")
    for vehicle, configured, expected in (("porter", 87, 89), ("porter", 89, 89),
                                          ("porter", 100, 100), ("other", 87, 87)):
      controller = NS(CP=NS(carFingerprint=vehicle))
      env = {"self": controller, "Params": lambda configured=configured: NS(get_int=lambda key: configured),
             "CAR": NS(HYUNDAI_PORTER_II_EV="porter"), "porter_steer_request_frames": porter_steer_request_frames}
      exec(code, env)
      self.assertEqual(controller.max_angle_frames, expected)

  @classmethod
  def setUpClass(cls):
    directory = Path(__file__).resolve().parents[1]
    import importlib.util
    spec = importlib.util.spec_from_file_location("porter_message", directory / "porter.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cls.buttons_class = module.PorterCruiseButtons
    tree = ast.parse((directory / "carcontroller.py").read_text(encoding="utf-8"))
    function = next(n for c in tree.body if isinstance(c, ast.ClassDef) and c.name == "CarController"
                    for n in c.body if isinstance(n, ast.FunctionDef) and n.name == "create_button_messages")
    for arg in function.args.args:
      arg.annotation = None
    function.returns = None
    env = {"CAR": NS(HYUNDAI_PORTER_II_EV="porter"), "Buttons": NS(NONE=0), "DT_CTRL": .01,
           "CV": NS(MS_TO_KPH=3.6), "structs": NS(CarState=NS(GearShifter=NS(drive="drive"))),
           "hyundaican": NS(create_clu11_button=lambda packer, frame, clu, button, cp: button),
           "cloudlog": NS(info=lambda *args: None)}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "actual_create_button_messages", "exec"), env)
    cls.function = staticmethod(env["create_button_messages"])

  def setUp(self):
    from opendbc.car.hyundai.porter_main_set import PorterMainSet
    self.controller = NS(porter_main_set=PorterMainSet(), porter_main_params=NS(get_bool=lambda key: False), CP=NS(carFingerprint="porter", safetyConfigs=[]), frame=0, packer=None,
                         porter_buttons=self.buttons_class(), speed_from_pcm=0,
                         button_spam1=8, button_spam2=30)
    self.cc = NS(enabled=True, cruiseControl=NS(cancel=False, resume=False),
                 hudControl=NS(setSpeed=55/3.6))
    self.cs = NS(is_metric=True, cruise_buttons=[0], main_buttons=[0],
                 clu11={"CF_Clu_AliveCnt1": 0, "CF_Clu_CruiseSwMain": 0},
                 cp=NS(ts_nanos={"CLU11": {"counter": 1_000_000_000}}, _last_update_nanos=1_000_000_000),
                 out=NS(vEgo=50/3.6, cruiseState=NS(enabled=True, available=True, speed=50/3.6), canValid=True,
                        accFaulted=False, gasPressed=False, standstill=False,
                        gearShifter="drive", brakePressed=False, brakeHoldActive=False, parkingBrake=False))

  def tick(self, frame):
    self.controller.frame = frame
    self.cs.cp._last_update_nanos = 1_000_000_000 + frame * 10_000_000
    self.cs.cp.ts_nanos["CLU11"]["counter"] = self.cs.cp._last_update_nanos
    return self.function(self.controller, self.cc, self.cs, True)

  def test_delayed_retry_slot_reaches_packer_once_per_stock_sample(self):
    self.controller.porter_buttons.retry_sample_delay = .01
    outputs = []
    for tick in range(12):
      self.controller.frame = tick
      self.cs.cp._last_update_nanos = 1_000_000_000 + tick * 10_000_000
      self.cs.cp.ts_nanos["CLU11"]["counter"] = 1_000_000_000 + (tick // 2) * 20_000_000
      self.cs.clu11["CF_Clu_AliveCnt1"] = tick // 2
      messages = self.function(self.controller, self.cc, self.cs, True)
      if messages:
        outputs.append((tick, messages))
    self.assertEqual(outputs, [(1, [1]), (3, [1]), (5, [1]), (7, [0]), (9, [0])])

  def test_learned_slot_survives_manual_and_disabled_message_path(self):
    self.controller.porter_buttons.retry_sample_delay = .01

    def tick(frame):
      self.controller.frame = frame
      self.cs.cp._last_update_nanos = 1_000_000_000 + frame * 10_000_000
      self.cs.cp.ts_nanos["CLU11"]["counter"] = 1_000_000_000 + (frame // 2) * 20_000_000
      self.cs.clu11["CF_Clu_AliveCnt1"] = (frame // 2) % 16
      return self.function(self.controller, self.cc, self.cs, True)

    self.assertEqual(tick(0), [])
    self.assertEqual(tick(1), [1])
    self.cs.out.cruiseState.speed = 51 / 3.6
    for frame in range(2, 6):
      tick(frame)
    self.cs.cruise_buttons = [2]
    self.assertEqual(tick(6), [])
    self.assertEqual(self.controller.porter_buttons.retry_sample_delay, .01)
    self.cs.cruise_buttons = [0]
    self.cc.enabled = False
    self.cs.out.cruiseState.enabled = False
    for frame in range(7, 20):
      self.assertEqual(tick(frame), [])
    self.assertEqual(self.controller.porter_buttons.requests, 1)
    self.assertEqual(self.controller.porter_buttons.retry_sample_delay, .01)
    self.cc.enabled = True
    self.cs.out.cruiseState.enabled = True
    self.assertEqual(tick(50), [])
    self.assertEqual(tick(51), [1])

  def test_explicit_zero_release_reaches_packer(self):
    self.assertEqual(self.tick(0), [1])
    self.assertEqual(self.tick(12), [0])
    self.assertEqual(self.tick(14), [0])
    self.assertEqual(self.tick(16), [])
    self.assertEqual(self.controller.porter_button_status[0], "waiting_ack")

  def test_brake_releases_pending_press(self):
    self.tick(0)
    self.cs.out.brakePressed = True
    self.assertEqual(self.tick(2), [0])
    self.assertEqual(self.tick(4), [])

  def test_brake_between_stock_frames_preserves_release_to_packer(self):
    self.assertEqual(self.tick(0), [1])
    self.controller.frame = 1
    self.cs.cp._last_update_nanos += 10_000_000
    self.cs.out.brakePressed = True
    self.assertEqual(self.function(self.controller, self.cc, self.cs, True), [])
    self.cs.out.brakePressed = False
    self.assertEqual(self.tick(4), [0])
    self.assertEqual(self.tick(6), [])
    self.assertEqual(self.controller.porter_buttons.requests, 1)

  def test_rx_gap_releases_before_restarting_buttons(self):
    self.assertEqual(self.tick(0), [1])
    self.controller.frame = 12
    self.cs.cp._last_update_nanos += 120_000_000
    self.assertEqual(self.function(self.controller, self.cc, self.cs, True), [])
    self.assertEqual(self.tick(14), [0])
    self.assertEqual(self.tick(16), [])
    self.assertEqual(self.controller.porter_buttons.requests, 1)

  def test_opposite_oem_speed_on_duplicate_sample_releases_and_keeps_fault(self):
    # Recorded timing: SET- at 0/10/40ms, OEM 32->42 at 50ms while CLU11
    # is unchanged. The release was lost before the pending-release fix.
    self.cc.hudControl.setSpeed = 30.81 / 3.6
    self.cs.out.cruiseState.speed = 32 / 3.6
    self.assertEqual(self.tick(0), [2])
    self.assertEqual(self.tick(1), [2])
    self.assertEqual(self.tick(4), [2])
    self.controller.frame = 5
    self.cs.cp._last_update_nanos += 10_000_000
    self.cs.out.cruiseState.speed = 42 / 3.6
    self.assertEqual(self.function(self.controller, self.cc, self.cs, True), [])
    self.assertEqual(self.controller.porter_buttons.status, "wrong_direction")
    self.assertEqual(self.tick(6), [0])
    self.assertEqual(self.tick(8), [])
    self.assertEqual(self.controller.porter_buttons.status, "fault")
    self.assertTrue(self.controller.porter_buttons.fault)
    self.assertEqual((self.controller.porter_buttons.requests, self.controller.porter_buttons.acks), (1, 0))

  def test_no_template_no_frame_and_pcm_policy(self):
    self.cs.clu11 = None
    self.assertEqual(self.tick(0), [])
    self.setUp()
    self.controller.speed_from_pcm = 1
    self.assertEqual(self.tick(0), [])

  def test_fractional_target_jitter_does_not_reach_packer(self):
    for frame, target in enumerate((50.49, 50.51, 50.7, 49.49, 49.51, 49.2)):
      self.cc.hudControl.setSpeed = target / 3.6
      self.assertEqual(self.tick(frame * 2), [])
    self.assertEqual(self.controller.porter_buttons.requests, 0)
    self.cc.hudControl.setSpeed = 49 / 3.6
    self.assertEqual(self.tick(20), [2])

  def test_main_auto_set_reaches_packer_and_stops_on_brake(self):
    self.controller.porter_main_params.get_bool = lambda key: True
    self.controller.CP.safetyConfigs = [NS(safetyParam=9217)]
    self.cs.out.cruiseState.enabled = False
    self.cs.out.cruiseState.speed = 0
    self.cc.cruiseControl.resume = True
    self.cs.main_buttons = [1]
    self.assertEqual(self.tick(0), [])
    self.cs.main_buttons = [0]
    outputs = []
    for frame in range(1, 60):
      outputs.extend((frame, value) for value in self.tick(frame))
    self.assertEqual(outputs[:4], [(51, 2), (52, 2), (53, 2), (54, 0)])
    self.cs.out.brakePressed = True
    self.tick(60)
    self.cs.out.brakePressed = False
    for frame in range(61, 200):
      self.assertEqual(self.tick(frame), [])


if __name__ == "__main__":
  unittest.main()
