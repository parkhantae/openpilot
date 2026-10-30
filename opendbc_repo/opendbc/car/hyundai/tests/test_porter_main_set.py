import unittest
from opendbc.car.hyundai.porter_main_set import PorterMainSet
from opendbc.car.hyundai.porter import porter_auto_set_speed_valid


class TestPorterMainSet(unittest.TestCase):
  def test_actual_interface_and_controller_select_versioned_startup_profile(self):
    import ast
    from pathlib import Path
    from types import SimpleNamespace as NS
    from opendbc.car.hyundai.values import HyundaiFlags, HyundaiSafetyFlags
    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root / 'interface.py').read_text())
    block = next(n for n in ast.walk(tree) if isinstance(n, ast.If) and
                 ast.unparse(n.test) == 'candidate == CAR.HYUNDAI_PORTER_II_EV')
    code = compile(ast.Module(body=[block], type_ignores=[]), 'actual_porter_profile', 'exec')
    for enabled, engage, expected in ((False,2,1025), (True,0,11265), (True,2,60417)):
      ret = NS(flags=0)
      exec(code, dict(candidate='porter', CAR=NS(HYUNDAI_PORTER_II_EV='porter'), ret=ret,
                      params=NS(get_bool=lambda key,e=enabled:e, get_int=lambda key,e=engage:e),
                      HyundaiFlags=HyundaiFlags, HyundaiSafetyFlags=HyundaiSafetyFlags,
                      structs=NS(CarParams=NS(SafetyModel=NS(hyundai='hyundai'))),
                      get_safety_config=lambda model,param:NS(safetyParam=param)))
      self.assertEqual(ret.safetyConfigs[0].safetyParam | HyundaiSafetyFlags.EV_GAS, expected)
    tree = ast.parse((root / 'carcontroller.py').read_text())
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.Assign) and
                ast.unparse(n.targets[0]) == 'self.porter_main_set')
    code = compile(ast.Module(body=[node], type_ignores=[]), 'actual_porter_startup_init', 'exec')
    for profile in (1025,9217,11265,25601,58369,60417):
      obj = NS()
      exec(code, dict(self=obj, CP=NS(safetyConfigs=[NS(safetyParam=profile)]), PorterMainSet=PorterMainSet))
      self.assertEqual(obj.porter_main_set.allow_startup_gas, profile in (58369,60417))
      self.assertEqual(obj.porter_main_set.main, profile in (25601,58369,60417))

  def test_startup_gas_is_one_attempt_per_fresh_pedal_cycle_without_main_proof(self):
    self.state = PorterMainSet(initial_main=True, allow_startup_gas=True)
    outputs = []
    for t in range(500):
      gas = 20 <= t < 100
      b = self.tick(t, gas_pressed=gas, request=not gas)
      if b is not None:
        outputs.append((t, b))
    self.assertEqual(outputs, [(100, 2), (102, 2), (104, 2), (106, 2), (108, 2), (110, 2), (112, 0)])
    self.assertFalse(self.state.main_known)
    self.assertFalse(self.state.armed)

  def test_startup_gas_held_at_boot_requires_release_then_new_press(self):
    self.state = PorterMainSet(initial_main=True, allow_startup_gas=True)
    for t in range(200):
      self.assertIsNone(self.tick(t, gas_pressed=t<100, request=t>=100))
    for t in range(200, 240):
      self.assertIsNone(self.tick(t, gas_pressed=True, request=False))
    self.assertEqual(self.tick(240), 2)
    self.assertEqual(self.tick(242, stock_enabled=True), 0)
    self.assertTrue(self.state.main_known)

  def test_startup_grant_expires_without_delayed_engagement(self):
    self.state = PorterMainSet(initial_main=True, allow_startup_gas=True)
    self.state.next_request = 3.
    for t in range(400):
      self.assertIsNone(self.tick(t, gas_pressed=20<=t<100, request=not 20<=t<100))
    self.assertFalse(self.state.startup_grant)

  def test_startup_pedal_cannot_bypass_main_off_cancel_brake_or_option(self):
    for override in (dict(main_pressed=True), dict(manual_button=4), dict(blocked=True), dict(configured=False)):
      self.state = PorterMainSet(initial_main=True, allow_startup_gas=True)
      for t in range(100):
        self.tick(t, gas_pressed=t>=20, request=t<20)
      self.assertIsNone(self.tick(100, **override))
      for t in range(101, 250):
        self.assertIsNone(self.tick(t))
    self.state = PorterMainSet(initial_main=False, allow_startup_gas=True)
    for t in range(250):
      self.assertIsNone(self.tick(t, gas_pressed=20<=t<100, request=not 20<=t<100))

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
    output = [(t, b) for t in range(3, 400) if (b := self.tick(t)) is not None]
    self.assertEqual(output[:7], [(52, 2), (54, 2), (56, 2), (58, 2), (60, 2), (62, 2), (64, 0)])
    self.assertTrue(all(b in (0, 2) for _, b in output))
    self.assertGreaterEqual(output[7][0] - output[6][0], 300)

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

  def test_gas_release_above_floor_requests_set_without_confirmation_dwell(self):
    self.arm()
    for t in range(3, 100):
      self.assertIsNone(self.tick(t, gas_pressed=True, request=False))
    self.assertEqual(self.tick(100), 2)

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
      self.assertEqual(self.tick(130), 2)

  def prepare_revoked_pedal_release(self, **kw):
    self.arm()
    self.tick(4, blocked=True, **kw)
    for t in range(5, 130):
      self.assertIsNone(self.tick(t, gas_pressed=100 <= t, request=False, **kw))
    self.assertFalse(self.state.armed)

  def test_log556_rearm_keeps_release_during_brief_lead_target_block(self):
    for pedal_only in (False, True):
      with self.subTest(pedal_only=pedal_only):
        self.setUp()
        self.prepare_revoked_pedal_release(pedal_only=pedal_only)
        # Target 29.82 at release, then above 30 about 66ms later. Neither
        # the blocked target nor recovery between RX samples can send SET.
        for t in range(130, 137):
          self.assertIsNone(self.tick(t, request=False, pedal_only=pedal_only))
          self.assertFalse(self.state.armed)
        self.assertIsNone(self.tick(137, pedal_only=pedal_only))
        self.assertTrue(self.state.armed)
        self.assertAlmostEqual(self.state.gas_release_since, 1.30)
        self.assertEqual(self.tick(138, pedal_only=pedal_only), 2)

  def test_rearm_release_observation_has_exact_100ms_expiry(self):
    for recovery, expected in ((140, 2), (141, None)):
      with self.subTest(recovery=recovery):
        self.setUp()
        self.prepare_revoked_pedal_release(pedal_only=True)
        for t in range(130, recovery):
          self.assertIsNone(self.tick(t, request=False, pedal_only=True))
        self.assertEqual(self.tick(recovery, pedal_only=True), expected)
        if expected is None:
          for t in range(recovery+1, 300):
            self.assertIsNone(self.tick(t, pedal_only=True))
          self.assertFalse(self.state.armed)

  def test_rearm_requires_vehicle_eligibility_at_release_and_through_recovery(self):
    for loss in (130, 135):
      with self.subTest(loss=loss):
        self.setUp()
        self.prepare_revoked_pedal_release(pedal_only=True)
        for t in range(130, 137):
          self.assertIsNone(self.tick(t, request=False, release_eligible=t != loss, pedal_only=True))
        for t in range(137, 300):
          self.assertIsNone(self.tick(t, pedal_only=True))
        self.assertFalse(self.state.armed)

  def test_actual_controller_separates_vehicle_release_eligibility_from_target(self):
    import ast
    from pathlib import Path
    from types import SimpleNamespace as NS
    tree = ast.parse((Path(__file__).resolve().parents[1] / 'carcontroller.py').read_text())
    names = ('main_set_vehicle_ready', 'main_set')
    nodes = [n for n in ast.walk(tree) if isinstance(n, ast.Assign) and
             isinstance(n.targets[0], ast.Name) and n.targets[0].id in names]
    code = compile(ast.Module(body=nodes, type_ignores=[]), 'actual_porter_release_eligibility', 'exec')
    for speed, metric, available, gear, target, expected in (
      (33,True,True,'drive',False,(True,False)),
      (33,True,True,'drive',True,(True,True)),
      (29.875,True,True,'drive',True,(False,False)),
      (33,False,True,'drive',True,(False,False)),
      (33,True,False,'drive',True,(False,False)),
      (33,True,True,'neutral',True,(False,False)),
    ):
      with self.subTest(speed=speed,metric=metric,available=available,gear=gear,target=target):
        calls = []
        obj = NS(frame=100, CP=NS(safetyConfigs=[NS(safetyParam=60417)]), speed_from_pcm=0,
                 porter_main_params=NS(get_bool=lambda _: True),
                 porter_main_set=NS(update=lambda *args,results=calls,**kwargs: results.append(kwargs)))
        out = NS(cruiseState=NS(available=available,enabled=False),gasPressed=False,gearShifter=gear,
                 vEgo=speed/3.6,vEgoCluster=speed/3.6,wheelSpeeds=NS(fl=speed/3.6,rr=speed/3.6),
                 canValid=True,accFaulted=False,brakePressed=False,brakeHoldActive=False,parkingBrake=False)
        cs = NS(out=out,is_metric=metric,main_buttons=[0],cruise_buttons=[0],
                clu11={'CF_Clu_AliveCnt1': 0,'CF_Clu_CruiseSwMain': 0})
        exec(code,dict(self=obj,CS=cs,CC=NS(enabled=False,latActive=False,cruiseControl=NS(resume=target,cancel=False)),
                       fresh=True,timestamp=1,cancel_busy=False,DT_CTRL=.01,
                       structs=NS(CarState=NS(GearShifter=NS(drive='drive'))),
                       porter_auto_set_speed_valid=porter_auto_set_speed_valid))
        self.assertEqual((calls[0]['release_eligible'],calls[0]['request']),expected)

  def test_rearm_recovery_does_not_renew_release_or_queue_behind_retry(self):
    for wait, sent_key in ((0., 70), (3., None)):
      with self.subTest(wait=wait, sent_key=sent_key):
        self.setUp()
        self.prepare_revoked_pedal_release(pedal_only=True)
        self.state.next_request = wait
        for t in range(130, 139):
          self.assertIsNone(self.tick(t, request=False, pedal_only=True))
        self.state.sent_key = sent_key
        # A valid target at 90ms cannot restart the original 100ms cue.
        for t in range(139, 400):
          self.assertIsNone(self.tick(t, pedal_only=True))
        for t in range(400, 430):
          self.assertIsNone(self.tick(t, gas_pressed=True, request=False, pedal_only=True))
        self.assertEqual(self.tick(430, pedal_only=True), 2)

  def test_pending_rearm_release_is_revoked_by_driver_or_invalid_input(self):
    for override in (dict(blocked=True), dict(manual_button=4), dict(main_pressed=True),
                     dict(configured=False), dict(stock_enabled=True)):
      with self.subTest(override=override):
        self.setUp()
        self.prepare_revoked_pedal_release(pedal_only=True)
        for t in range(130, 135):
          self.assertIsNone(self.tick(t, request=False, pedal_only=True))
        self.assertIsNone(self.tick(135, request=False, pedal_only=True, **override))
        for t in range(136, 300):
          self.assertIsNone(self.tick(t, pedal_only=True))

  def test_pending_rearm_release_does_not_survive_clock_gap(self):
    self.prepare_revoked_pedal_release(pedal_only=True)
    self.tick(130, request=False, pedal_only=True)
    self.assertIsNone(self.tick(141, pedal_only=True))
    for t in range(142, 300):
      self.assertIsNone(self.tick(t, pedal_only=True))
    self.assertFalse(self.state.armed)

  def test_short_or_repressed_pedal_cannot_reuse_pending_rearm_release(self):
    for short_press in (False, True):
      with self.subTest(short_press=short_press):
        self.setUp()
        self.prepare_revoked_pedal_release(pedal_only=True)
        if not short_press:
          # Discard the qualified release when the driver presses again.
          self.tick(130, request=False, pedal_only=True)
          self.tick(131, gas_pressed=True, request=False, pedal_only=True)
        else:
          self.state = PorterMainSet()
          self.arm()
          self.tick(4, blocked=True, pedal_only=True)
          for t in range(5, 132):
            self.tick(t, gas_pressed=t >= 128, request=False, pedal_only=True)
        for t in range(132, 300):
          self.assertIsNone(self.tick(t, pedal_only=True))
        self.assertFalse(self.state.armed)

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

  def test_log547_release_requests_set_as_soon_as_brief_lead_cap_clears(self):
    self.arm()
    for t in range(3, 100):
      self.tick(t, gas_pressed=True, request=False)
    for t in range(100, 105):
      self.assertIsNone(self.tick(t, request=False))
    self.assertIsNone(self.tick(105))  # recovery between RX updates
    self.assertEqual(self.tick(106), 2)

  def test_request_loss_stops_immediate_release_set_and_preserves_quiet_period(self):
    self.arm()
    for t in range(3, 100):
      self.tick(t, gas_pressed=True, request=False)
    self.assertEqual(self.tick(100), 2)
    self.assertEqual(self.tick(102, request=False), 0)
    for t in range(103, 153):
      self.assertIsNone(self.tick(t))

  def test_release_waits_for_unsent_sample_and_keeps_native_main_settling(self):
    self.arm()
    for t in range(3, 40):
      self.tick(t, gas_pressed=True, request=False)
    for t in range(40, 50):
      self.assertIsNone(self.tick(t))
    self.assertEqual(self.tick(50), 2)  # MAIN still requires 500ms
    self.state = PorterMainSet()
    self.arm()
    for t in range(3, 100):
      self.tick(t, gas_pressed=True, request=False)
    self.state.sent_key = 50
    self.assertIsNone(self.tick(100))
    self.assertIsNone(self.tick(101))
    self.assertEqual(self.tick(102), 2)

  def test_repeated_release_cannot_bypass_retry_limits_after_interrupted_pulses(self):
    self.arm()
    starts = []
    for t in range(3, 1001):
      # A new pedal tap after every 20ms interrupts each attempted SET. Even
      # those incomplete pulses must consume the native one-/three-second gap.
      gas = t < 100 or t % 100 in (2, 3)
      was = self.state.pressing
      button = self.tick(t, gas_pressed=gas, request=not gas)
      if button == 2 and not was:
        starts.append(t)
    self.assertEqual(starts, [100, 404, 716])

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
    self.assertEqual(self.tick(100), 2)

  def test_unanswered_set_waits_for_real_on_and_retries_on_new_rx_only(self):
    self.arm()
    starts = []
    for t in range(3, 370):
      was = self.state.pressing
      button = self.tick(t)
      if button == 2 and not was:
        starts.append(t)
        self.assertEqual(t % 2, 0)
    self.assertEqual(starts, [52, 364])
    self.assertEqual(self.state.requests, 2)
    self.assertEqual(self.state.timeouts, 1)
    self.assertEqual(self.state.acks, 0)
    self.assertEqual(self.tick(370, stock_enabled=True), 0)
    self.assertEqual(self.state.acks, 1)
    self.assertEqual(self.state.response, "engaged")
    self.assertFalse(self.state.awaiting_stock)
    self.tick(371, stock_enabled=True)
    self.assertEqual(self.state.acks, 1)

  def test_physical_set_brake_and_late_on_do_not_ack_automatic_request(self):
    for change in (dict(manual_button=2, stock_enabled=True), dict(blocked=True, stock_enabled=True)):
      self.setUp()
      self.arm()
      for t in range(3, 53):
        self.tick(t)
      self.tick(54, **change)
      self.assertEqual(self.state.acks, 0)
      self.assertFalse(self.state.awaiting_stock)
    self.setUp()
    self.arm()
    for t in range(3, 106):
      self.tick(t)
    self.tick(106, stock_enabled=True)
    self.assertEqual(self.state.acks, 0)
    self.assertEqual(self.state.timeouts, 1)

  def test_request_loss_releases_but_still_observes_in_flight_set_result(self):
    self.arm()
    for t in range(3, 100):
      self.tick(t, gas_pressed=True, request=False)
    self.assertEqual(self.tick(100), 2)
    self.assertEqual(self.tick(102, request=False), 0)
    self.assertEqual(self.state.acks, 0)
    self.assertTrue(self.state.awaiting_stock)
    self.tick(104, request=False, stock_enabled=True)
    self.assertEqual(self.state.acks, 1)
    self.assertEqual(self.state.response, "engaged")

  def test_pedal_release_on_old_unsent_sample_waits_for_next_rx(self):
    self.arm()
    for t in range(3, 101):
      self.tick(t, gas_pressed=True, request=False)
    self.assertIsNone(self.tick(101))  # old but unsent RX sample
    self.assertEqual(self.tick(102), 2)
    self.assertIsNone(self.tick(103))
    # A missing/stale period interrupts the pulse; it cannot flush an old SET.
    self.assertEqual(self.tick(104, blocked=True), 0)
    self.assertIsNone(self.tick(105))

  def test_set_frames_never_reuse_samples_when_deadline_or_pedal_changes(self):
    self.arm()
    for t in range(3, 600):
      button = self.tick(t, gas_pressed=90 <= t < 101)
      if button == 2:
        self.assertEqual(t % 2, 0)
    self.assertGreaterEqual(self.state.timeouts, 2)

  def test_actual_controller_diagnostics_format_response_counts(self):
    import ast
    from pathlib import Path
    from types import SimpleNamespace as NS
    tree = ast.parse((Path(__file__).resolve().parents[1] / 'carcontroller.py').read_text())
    method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'create_button_messages')
    branch = method.body[1].body
    index = next(i for i, n in enumerate(branch) if isinstance(n, ast.Assign) and
                 ast.unparse(n.targets[0]) == 'main_status')
    code = compile(ast.Module(body=branch[index:index+2], type_ignores=[]), 'actual_main_set_diagnostics', 'exec')
    obj = NS(porter_main_set=self.state, CP=NS(safetyConfigs=[NS(safetyParam=58369)]), frame=100)
    cc = NS(cruiseControl=NS(resume=True))
    cs = NS(out=NS(cruiseState=NS(enabled=False), vEgo=40/3.6, vEgoCluster=42/3.6, gasPressed=False))
    messages = []
    env = dict(self=obj, CC=cc, CS=cs, DT_CTRL=.01, porter_auto_set_speed_valid=porter_auto_set_speed_valid, CV=NS(MS_TO_KPH=3.6), fresh=True, manual=False,
               cloudlog=NS(info=lambda fmt, *args: messages.append(fmt % args)))
    self.arm()
    for t in range(3, 104):
      self.tick(t)
    exec(code, env)
    self.assertIn('req=1 ack=0 noack=1 response=no_response awaiting=False', messages[-1])

  def test_invalid_inputs_interrupt_pending_feedback_without_false_timeout(self):
    self.arm()
    for t in range(3, 53):
      self.tick(t)
    self.tick(54, blocked=True)
    self.assertEqual(self.state.response, "interrupted")
    for t in range(55, 120):
      self.tick(t)
    self.assertEqual(self.state.acks, 0)
    self.assertEqual(self.state.timeouts, 0)

  def test_inactive_controls_require_pedal_and_request_on_each_fresh_release(self):
    self.arm()
    starts = []
    for t in range(3, 700):
      gas = 100 <= t < 130 or 300 <= t < 330 or 500 <= t < 530
      was = self.state.pressing
      button = self.tick(t, pedal_only=True, gas_pressed=gas, request=not gas)
      if button == 2 and not was:
        starts.append(t)
    self.assertEqual(starts, [130, 530])
    self.assertEqual(self.state.requests, 2)
    self.assertEqual(self.state.timeouts, 2)

  def test_inactive_controls_release_cannot_wait_behind_retry_backoff(self):
    self.arm()
    self.state.next_request = 3.
    for t in range(3, 400):
      self.assertIsNone(self.tick(t, pedal_only=True, gas_pressed=100<=t<130))
    for t in range(400, 430):
      self.assertIsNone(self.tick(t, pedal_only=True, gas_pressed=True))
    self.assertEqual(self.tick(430, pedal_only=True), 2)

  def test_inactive_release_keeps_main_brake_cancel_and_option_guards(self):
    for override in (dict(blocked=True),dict(manual_button=4),dict(main_pressed=True),dict(configured=False)):
      self.setUp()
      self.arm()
      for t in range(3, 100):
        self.tick(t, gas_pressed=True, request=False, pedal_only=True)
      self.assertIsNone(self.tick(100, pedal_only=True, **override))
      for t in range(101, 200):
        self.assertIsNone(self.tick(t, pedal_only=True))

  def test_inactive_transition_cannot_inherit_standby_dwell_or_timer_pulse(self):
    self.arm()
    for t in range(3, 200):
      self.assertIsNone(self.tick(t, pedal_only=True))
    for t in range(200, 250):
      self.assertIsNone(self.tick(t))
    self.assertEqual(self.tick(250), 2)  # active mode gets its own 500ms dwell
    self.setUp()
    self.arm()
    for t in range(3, 52):
      self.tick(t)
    self.assertEqual(self.tick(52), 2)
    self.assertIsNone(self.tick(53, pedal_only=True))
    self.assertEqual(self.tick(54, pedal_only=True), 0)  # release timer-only pulse
    for t in range(55, 400):
      self.assertIsNone(self.tick(t, pedal_only=True))
    for t in range(400, 430):
      self.assertIsNone(self.tick(t, pedal_only=True, gas_pressed=True))
    self.assertEqual(self.tick(430, pedal_only=True), 2)

  def test_confirmed_on_retains_short_retry_window_for_next_fresh_release(self):
    self.arm()
    for t in range(3, 100):
      self.tick(t, gas_pressed=True, request=False)
    self.assertEqual(self.tick(100), 2)
    self.assertEqual(self.tick(102, stock_enabled=True), 0)
    for t in range(103, 150):
      self.tick(t, stock_enabled=True)
    for t in range(150, 220):
      self.assertIsNone(self.tick(t, gas_pressed=True, request=False))
    self.assertEqual(self.tick(220), 2)  # positive ON did not become a 3s failure wait
    self.assertEqual(self.state.acks, 1)
