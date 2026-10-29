import unittest
from opendbc.car.hyundai.porter_main_set import PorterMainSet


class TestPorterMainSet(unittest.TestCase):
  def setUp(self):
    self.state = PorterMainSet()

  def tick(self, tick, **kw):
    args = dict(main_pressed=False, manual_button=0, blocked=False, request=True,
                stock_enabled=False, configured=True)
    args.update(kw)
    return self.state.update(tick * .01, tick // 2, **args)

  def arm(self):
    self.tick(0, main_pressed=True)
    self.tick(2)

  def test_no_main_or_disabled_setting_never_starts(self):
    for t in range(200):
      self.assertIsNone(self.tick(t))
    self.state = PorterMainSet()
    for t in range(200):
      self.assertIsNone(self.tick(t, configured=False, main_pressed=t < 10))

  def test_set_only_confirmation_pulse_release_and_retry_limit(self):
    self.arm()
    output = [(t, b) for t in range(3, 180) if (b := self.tick(t)) is not None]
    self.assertEqual(output[:7], [(52, 2), (54, 2), (56, 2), (58, 2), (60, 2), (62, 2), (64, 0)])
    self.assertTrue(all(b in (0, 2) for _, b in output))
    self.assertGreaterEqual(output[7][0] - output[0][0], 100)

  def test_cancel_brake_main_off_and_live_off_disarm(self):
    for guard in (dict(manual_button=4), dict(blocked=True), dict(main_pressed=True), dict(configured=False)):
      self.setUp()
      self.arm()
      self.tick(4, **guard)
      self.tick(6)
      self.assertFalse(self.state.armed)
      for t in range(7, 90):
        self.assertIsNone(self.tick(t))

  def test_gas_or_low_speed_request_loss_resets_confirmation(self):
    self.arm()
    for t in range(3, 60):
      self.tick(t, request=t < 40)
    for t in range(60, 110):
      self.assertIsNone(self.tick(t))
    self.assertEqual(self.tick(110), 2)

  def test_stock_engagement_and_interruption_release(self):
    self.arm()
    for t in range(3, 53):
      self.tick(t)
    self.assertEqual(self.tick(54, stock_enabled=True), 0)
    for t in range(55, 100):
      self.assertIsNone(self.tick(t, stock_enabled=True))

  def test_stream_gap_requires_new_main(self):
    self.arm()
    self.assertIsNone(self.tick(50))
    self.assertFalse(self.state.armed)

  def test_manual_button_interrupt_does_not_transmit_release_over_driver(self):
    self.arm()
    for t in range(3, 53):
      self.tick(t)
    self.assertIsNone(self.tick(54, manual_button=4))
    self.assertIsNone(self.tick(56, manual_button=4))
    self.assertEqual(self.tick(58), 0)
    self.assertFalse(self.state.armed)

  def test_log544_manual_set_syncs_main_without_granting_authority(self):
    self.tick(0, stock_enabled=True, request=False)
    self.assertTrue(self.state.main)
    self.assertFalse(self.state.armed)
    self.tick(2, stock_enabled=True, main_pressed=True)
    self.assertFalse(self.state.main)
    self.tick(4, stock_enabled=True, main_pressed=True)
    self.assertFalse(self.state.main)  # delayed OEM OFF must not undo MAIN OFF
    self.tick(6, stock_enabled=False)
    self.tick(8, main_pressed=True)
    self.assertTrue(self.state.main)
    self.assertTrue(self.state.armed)
    self.tick(10, blocked=True)
    self.tick(12, stock_enabled=True)
    self.assertFalse(self.state.armed)  # feedback cannot undo brake/CANCEL revocation

  def test_actual_carstate_stock_edge_sync_and_main_off(self):
    import ast
    from pathlib import Path
    from types import SimpleNamespace as NS
    tree = ast.parse((Path(__file__).resolve().parents[1] / 'carstate.py').read_text())
    update = next(n for c in tree.body if isinstance(c, ast.ClassDef) and c.name == 'CarState'
                  for n in c.body if isinstance(n, ast.FunctionDef) and n.name == 'update')
    block = next(n for n in ast.walk(update) if isinstance(n, ast.If) and
                 any(isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and
                     call.func.id == 'update_porter_state' for call in ast.walk(n)))
    code = compile(ast.Module(body=block.body, type_ignores=[]), 'actual_porter_state_sync', 'exec')
    obj = NS(CP=NS(safetyConfigs=[NS(safetyParam=9217)]), main_enabled=False,
             main_buttons=[0], porter_main_stock_prev=False, is_metric=True)
    ret = NS(gearShifter='drive', cruiseState=NS(enabled=True, available=True, speed=40/3.6))
    env = dict(self=obj, ret=ret, cp=None, GearShifter=NS(drive='drive'), update_porter_state=lambda *args: None)
    exec(code, env)
    self.assertTrue(obj.main_enabled)
    obj.main_enabled = False
    obj.main_buttons = [1]
    exec(code, env)  # MAIN OFF while stock ON feedback is still arriving
    self.assertFalse(obj.main_enabled)
    ret.cruiseState.enabled = False
    obj.main_buttons = [0]
    exec(code, env)
    self.assertFalse(obj.main_enabled)

  def test_gas_release_above_floor_uses_short_confirmation(self):
    self.arm()
    for t in range(3, 100):
      self.assertIsNone(self.tick(t, gas_pressed=True, request=False))
    for t in range(100, 110):
      self.assertIsNone(self.tick(t))
    self.assertEqual(self.tick(110), 2)

  def test_release_with_blocked_target_does_not_queue_fast_set(self):
    self.arm()
    for t in range(3, 100):
      self.tick(t, gas_pressed=True, request=False)
    for t in range(100, 120):
      self.assertIsNone(self.tick(t, request=False))
    for t in range(120, 170):
      self.assertIsNone(self.tick(t))
    self.assertEqual(self.tick(170), 2)

  def test_release_cannot_bypass_brake_or_missing_main(self):
    for armed in (False, True):
      self.setUp()
      if armed:
        self.arm()
      for t in range(3, 100):
        self.tick(t, gas_pressed=True, request=False)
      self.tick(100, blocked=True)
      for t in range(101, 180):
        self.assertIsNone(self.tick(t))

  def test_new_gas_after_brake_or_cancel_rearms_without_main_cycle(self):
    for override in (dict(blocked=True), dict(manual_button=4)):
      self.setUp()
      self.arm()
      self.tick(4, **override)
      for t in range(5, 100):
        self.assertIsNone(self.tick(t))
      for t in range(100, 130):
        self.assertIsNone(self.tick(t, gas_pressed=True, request=False))
      for t in range(130, 140):
        self.assertIsNone(self.tick(t))
      self.assertEqual(self.tick(140), 2)

  def test_gas_held_through_brake_is_not_new_authorization(self):
    self.arm()
    for t in range(3, 100):
      self.tick(t, gas_pressed=True, request=False)
    self.tick(100, gas_pressed=True, blocked=True)
    for t in range(101, 130):
      self.tick(t, gas_pressed=True, request=False)
    for t in range(130, 200):
      self.assertIsNone(self.tick(t))
    self.assertFalse(self.state.armed)

  def test_main_off_never_rearms_from_gas(self):
    self.arm()
    self.tick(4, main_pressed=True)
    for t in range(5, 100):
      self.tick(t, gas_pressed=True, request=False)
    for t in range(100, 180):
      self.assertIsNone(self.tick(t))
    self.assertFalse(self.state.main)

  def test_engagement_feedback_ends_extended_set_immediately(self):
    self.arm()
    sent = [self.tick(t) for t in range(3, 60)]
    self.assertEqual(sent.count(2), 4)
    self.assertEqual(self.tick(60, stock_enabled=True), 0)
    for t in range(61, 90):
      self.assertIsNone(self.tick(t, stock_enabled=True))

  def test_log547_brief_lead_cap_at_release_preserves_fast_confirmation(self):
    self.arm()
    for t in range(3, 100):
      self.tick(t, gas_pressed=True, request=False)
    for t in range(100, 105):
      self.assertIsNone(self.tick(t, request=False))
    for t in range(105, 115):
      self.assertIsNone(self.tick(t))
    self.assertEqual(self.tick(115), 2)

  def test_request_chatter_restarts_continuous_confirmation(self):
    self.arm()
    for t in range(3, 100):
      self.tick(t, gas_pressed=True, request=False)
    for t in range(100, 110):
      self.assertIsNone(self.tick(t, request=t>=104))
    self.assertIsNone(self.tick(110, request=False))
    self.assertIsNone(self.tick(111, request=False))
    for t in range(112, 150):
      self.assertIsNone(self.tick(t))

  def test_initial_on_parity_does_not_authorize_without_physical_input(self):
    self.state = PorterMainSet(initial_main=True)
    for t in range(200):
      self.assertIsNone(self.tick(t, gas_pressed=t<100, request=t>=100))
    self.assertFalse(self.state.armed)
    self.assertFalse(self.state.main_known)

  def test_log54a_two_main_presses_end_in_authorized_standby(self):
    self.state = PorterMainSet(initial_main=True)
    self.tick(0, main_pressed=True, request=False)
    self.assertFalse(self.state.main)
    self.tick(2, request=False)
    self.tick(4, main_pressed=True, request=False)
    self.assertTrue(self.state.main)
    for t in range(5, 100):
      self.tick(t, gas_pressed=True, request=False)
    for t in range(100, 110):
      self.assertIsNone(self.tick(t))
    self.assertEqual(self.tick(110), 2)

  def test_unacknowledged_startup_tries_other_slot_and_learns_real_feedback(self):
    self.arm()
    starts=[]
    for t in range(3, 168):
      was_pressing=self.state.pressing
      b=self.tick(t)
      if b==2 and not was_pressing:
        starts.append(t)
    self.assertEqual(starts, [52,163])
    self.assertEqual(self.state.preferred_delay, 0.)
    self.assertEqual(self.state.pulse_delay, .01)
    self.assertEqual(self.tick(168,stock_enabled=True),0)
    self.assertEqual(self.state.preferred_delay,.01)
    self.tick(170,blocked=True)
    self.assertEqual(self.state.retry_delay,.01)

  def test_physical_set_does_not_learn_automatic_slot(self):
    self.arm()
    for t in range(3, 168):
      self.tick(t)
    self.tick(168,manual_button=2,stock_enabled=True)
    self.assertEqual(self.state.preferred_delay,0.)

  def test_unavailable_delayed_slot_has_bounded_fallback(self):
    self.arm()
    starts=[]
    for t in range(3, 200):
      was_pressing=self.state.pressing
      b=self.state.update(t*.01,t,main_pressed=False,manual_button=0,blocked=False,
                          request=True,stock_enabled=False,configured=True)
      if b==2 and not was_pressing:
        starts.append(t)
    self.assertEqual(starts,[52,168])
    self.assertEqual(self.state.pulse_delay,0.)
