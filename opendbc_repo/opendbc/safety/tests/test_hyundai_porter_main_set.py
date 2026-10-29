import unittest
from hyundai_porter_testlib import lib, packet, data, seed, init


class TestPorterMainSetSafety(unittest.TestCase):
  def startup_pedal(self, param=58369, **overrides):
    init(param)
    for tick in range(91):
      lib.set_timer(21000+tick*10000)
      if tick % 2 == 0:
        args = dict(speed=40, gas=20<=tick<90)
        args.update(overrides)
        seed(counter=tick//2, **args)

  def test_new_startup_profile_grants_one_bounded_set_not_controls(self):
    self.startup_pedal()
    self.assertFalse(lib.get_controls_allowed())
    self.assertFalse(self.tx(button=1, counter=46))
    for i in range(6):
      if i:
        lib.set_timer(921000+i*20000)
        seed(counter=45+i, speed=40)
      self.assertTrue(self.tx(counter=46+i))
    lib.set_timer(1041000)
    seed(counter=51, speed=40)
    self.assertFalse(self.tx(counter=52))
    self.assertTrue(self.tx(button=0, counter=52))
    lib.set_timer(3021000)
    seed(counter=52, speed=40)
    self.assertFalse(self.tx(counter=53))  # no blind retry after quiet period
    self.assertFalse(lib.get_controls_allowed())

  def test_startup_profile_and_all_existing_override_limits_are_required(self):
    for param in (1025, 9217, 25601):
      self.startup_pedal(param)
      self.assertFalse(self.tx(counter=46))
    for guard in (dict(speed=29), dict(speed=161), dict(brake=True), dict(hold=True),
                  dict(park=True), dict(drive=False), dict(main=True), dict(button=4), dict(gas=True)):
      self.startup_pedal(**guard)
      self.assertFalse(self.tx(counter=46), guard)

  def test_startup_unused_permission_expires_after_release(self):
    self.startup_pedal()
    lib.set_timer(1041000)
    seed(counter=46, speed=40)
    self.assertFalse(self.tx(counter=47))

  def test_startup_valid_observation_survives_native_timer_wrap(self):
    init(58369)
    for tick in range(91):
      lib.set_timer((0xffffffff-700000+tick*10000) & 0xffffffff)
      if tick % 2 == 0:
        seed(counter=tick//2, speed=40, gas=20<=tick<90)
    self.assertTrue(self.tx(counter=46))

  def test_host_startup_gas_and_native_agree_without_main_button(self):
    from opendbc.car.hyundai.porter_main_set import PorterMainSet
    init(58369)
    pulse = PorterMainSet(initial_main=True, allow_startup_gas=True)
    outputs = []
    for tick in range(500):
      lib.set_timer(21000+tick*10000)
      counter = tick//2
      gas = 20<=tick<100
      if tick % 2 == 0:
        seed(counter=counter, speed=40, gas=gas)
      b = pulse.update(tick*.01, counter, main_pressed=False, manual_button=0, blocked=False,
                       request=not gas, stock_enabled=False, configured=True, gas_pressed=gas)
      if b is not None:
        self.assertTrue(lib.safety_tx_hook(packet(0x4f1, data(0x4f1, button=b, counter=counter+1))), (tick,b))
        outputs.append(b)
    self.assertEqual(outputs, [2]*6+[0])
    self.assertFalse(pulse.main_known)
    self.assertFalse(lib.get_controls_allowed())

  def test_startup_held_gas_at_boot_is_not_a_new_driver_cycle(self):
    lib.set_safety_hooks(8, 58369)
    lib.init_tests()
    for tick in range(91):
      lib.set_timer(21000+tick*10000)
      if tick % 2 == 0:
        seed(counter=tick//2, speed=40, gas=tick<80)
    self.assertFalse(self.tx(counter=46))

  def test_startup_permission_is_revoked_by_override_before_transmission(self):
    for guard in (dict(brake=True), dict(hold=True), dict(park=True), dict(drive=False),
                  dict(button=4), dict(main=True)):
      self.startup_pedal()
      lib.set_timer(941000)
      seed(counter=46, speed=40, **guard)
      lib.set_timer(961000)
      seed(counter=47, speed=40)
      self.assertFalse(self.tx(counter=48), guard)

  def test_startup_stock_feedback_not_pedal_grant_enables_controls(self):
    self.startup_pedal()
    self.assertTrue(self.tx(counter=46))
    self.assertFalse(lib.get_controls_allowed())
    lib.set_timer(941000)
    seed(counter=46, speed=40, target=40)
    self.assertTrue(lib.get_controls_allowed())

  def test_startup_flag_without_initial_main_on_is_rejected(self):
    lib.set_safety_hooks(8, 41985)
    lib.init_tests()
    self.assertFalse(lib.safety_config_valid())

  def prepare(self, param=9217):
    init(param)
    lib.set_timer(21000)
    seed(counter=1, main=True, speed=40)
    for counter in range(2, 35):
      lib.set_timer(21000 + (counter - 1) * 20000)
      seed(counter=counter, speed=40)

  def tx(self, button=2, counter=3):
    return lib.safety_tx_hook(packet(0x4f1, data(0x4f1, button=button, counter=counter)))

  def test_opt_in_and_physical_main_required(self):
    for param in (1025, 9217):
      init(param)
      seed(counter=1, speed=40)
      self.assertFalse(self.tx(counter=2))
    self.prepare(1025)
    self.assertFalse(self.tx())
    self.prepare()
    self.assertFalse(lib.get_controls_allowed())
    self.assertFalse(self.tx(button=1))
    self.assertTrue(self.tx())
    self.assertFalse(lib.get_controls_allowed())
    self.assertFalse(self.tx())  # cannot reuse the OEM sample

  def test_bounded_pulse_and_retry(self):
    self.prepare()
    self.assertTrue(self.tx())
    for i in range(3, 8):
      lib.set_timer(681000 + (i - 2) * 20000)
      seed(counter=i, speed=40)
      self.assertTrue(self.tx(counter=i + 1))
    lib.set_timer(801000)
    seed(counter=8, speed=40)
    self.assertFalse(self.tx(counter=9))
    self.assertTrue(self.tx(button=0))
    self.assertFalse(self.tx(counter=9))

  def test_overrides_and_state_guards(self):
    for changes in (dict(brake=True), dict(park=True), dict(hold=True), dict(drive=False), dict(gas=True),
                    dict(speed=29), dict(speed=161), dict(main=True), dict(button=4)):
      with self.subTest(changes=changes):
        self.prepare()
        lib.set_timer(701000)
        seed(counter=3, **(dict(speed=40) | changes))
        self.assertFalse(self.tx(counter=4))

  def test_stale_inputs_block(self):
    self.prepare()
    lib.set_timer(1000000)
    self.assertFalse(self.tx())

  def test_only_stock_feedback_enables_controls(self):
    self.prepare()
    self.assertTrue(self.tx())
    self.assertFalse(lib.get_controls_allowed())
    lib.set_timer(701000)
    seed(counter=3, speed=40, target=40)
    self.assertTrue(lib.get_controls_allowed())

  def test_cancel_and_brake_do_not_rearm_on_release(self):
    for change in (dict(button=4), dict(brake=True)):
      self.prepare()
      lib.set_timer(701000)
      seed(counter=3, speed=40, **change)
      lib.set_timer(721000)
      seed(counter=4, speed=40)
      self.assertFalse(self.tx(counter=5))

  def test_limiter_and_wrong_counter_cannot_start(self):
    self.prepare()
    self.assertFalse(self.tx(counter=4))
    limiter = (1 << 13).to_bytes(8, 'little')
    self.assertTrue(lib.safety_rx_hook(packet(0x371, limiter)))
    self.assertFalse(self.tx())

  def test_main_press_must_be_confirmed_for_half_second(self):
    init(9217)
    lib.set_timer(21000)
    seed(counter=1, main=True, speed=40)
    lib.set_timer(41000)
    seed(counter=2, speed=40)
    self.assertFalse(self.tx())

  def test_log544_manual_engagement_syncs_main_parity(self):
    init(9217)
    lib.set_timer(21000)
    seed(counter=1, button=2, speed=40)
    lib.set_timer(41000)
    seed(counter=2, target=40, speed=40)
    lib.set_timer(61000)
    seed(counter=3, target=40, main=True, speed=40)  # MAIN OFF, feedback still ON
    lib.set_timer(81000)
    seed(counter=4, speed=40)
    self.assertFalse(self.tx(counter=5))
    lib.set_timer(101000)
    seed(counter=5, main=True, speed=40)  # MAIN ON again
    for counter in range(6, 34):
      lib.set_timer(101000 + (counter - 5) * 20000)
      seed(counter=counter, speed=40)
    self.assertTrue(self.tx(counter=34))

  def test_feedback_does_not_rearm_after_cancel(self):
    self.prepare()
    lib.set_timer(701000)
    seed(counter=3, speed=40, button=4)
    lib.set_timer(721000)
    seed(counter=4, speed=40, target=40)
    lib.set_timer(801000)
    seed(counter=8, speed=40)
    self.assertFalse(self.tx(counter=9))

  def test_bounded_cancel_release_uses_existing_native_permission(self):
    from opendbc.car.hyundai.porter_cancel import PorterCancelButtons
    from hyundai_porter_testlib import engage
    engage()
    pulse = PorterCancelButtons()
    emitted = []
    for tick in range(150):
      lib.set_timer(13000 + tick * 10000)
      counter = tick // 2 + 3
      if tick % 2 == 0:
        seed(counter=counter, target=42, speed=40)
      button = pulse.update(tick * .01, counter, requested=True, stock_enabled=True, preferred_delay=.01)
      if button is not None:
        emitted.append(button)
        self.assertTrue(lib.safety_tx_hook(packet(0x4f1, data(0x4f1, button=button, counter=counter+1))))
    self.assertIn(4, emitted)
    self.assertIn(0, emitted)
    self.assertNotIn(1, emitted)
    self.assertNotIn(2, emitted)

  def test_new_acceleration_release_rearms_after_override_only_with_main(self):
    for override, expected in ((dict(brake=True), True), (dict(button=4), True), (dict(main=True), False)):
      self.prepare()
      lib.set_timer(701000)
      seed(counter=3, speed=40, **override)
      lib.set_timer(721000)
      seed(counter=4, speed=40)
      self.assertFalse(self.tx(counter=5))
      for i in range(5, 16):
        lib.set_timer(721000+(i-4)*20000)
        seed(counter=i, speed=40, gas=i<15)
      self.assertEqual(self.tx(counter=16), expected)

  def test_gas_held_through_override_does_not_rearm(self):
    self.prepare()
    lib.set_timer(701000)
    seed(counter=3, speed=40, gas=True, brake=True)
    for i in range(4, 16):
      lib.set_timer(701000+(i-3)*20000)
      seed(counter=i, speed=40, gas=i<15)
    self.assertFalse(self.tx(counter=16))

  def test_startup_set_duration_bound_independent_of_frame_count(self):
    self.prepare()
    self.assertTrue(self.tx())
    for i in range(3, 9):
      lib.set_timer(681000+(i-2)*20000)
      seed(counter=i, speed=40)
    self.assertFalse(self.tx(counter=9))  # 120ms elapsed, only one frame sent

  def test_seventh_startup_set_frame_is_blocked_before_time_limit(self):
    self.prepare()
    self.assertTrue(self.tx())
    for i in range(3, 8):
      lib.set_timer(681000+(i-2)*10000)
      seed(counter=i, speed=40)
      self.assertTrue(self.tx(counter=i+1))
    lib.set_timer(741000)
    seed(counter=8, speed=40)
    self.assertFalse(self.tx(counter=9))

  def test_initial_on_seed_never_authorizes_transmission_or_pedal_rearm(self):
    init(25601)
    for counter in range(1, 40):
      lib.set_timer(1000+counter*20000)
      seed(counter=counter, speed=40, gas=counter<25)
      self.assertFalse(self.tx(counter=counter+1))
    self.assertFalse(lib.get_controls_allowed())

  def test_initial_on_two_main_presses_preserve_correct_native_parity(self):
    init(25601)
    lib.set_timer(21000)
    seed(counter=1, main=True, speed=40)
    lib.set_timer(41000)
    seed(counter=2, speed=40)
    self.assertFalse(self.tx())
    lib.set_timer(61000)
    seed(counter=3, main=True, speed=40)
    for counter in range(4, 36):
      lib.set_timer(61000+(counter-3)*20000)
      seed(counter=counter, speed=40)
    self.assertTrue(self.tx(counter=36))
    self.assertFalse(lib.get_controls_allowed())

  def test_fresh_rx_startup_retries_and_feedback_pass_native(self):
    from opendbc.car.hyundai.porter_main_set import PorterMainSet
    init(9217)
    pulse=PorterMainSet()
    starts=[]
    for tick in range(180):
      lib.set_timer(21000+tick*10000)
      counter=tick//2
      stock=tick>=168
      if tick % 2==0:
        seed(counter=counter,main=tick==0,target=40 if stock else 0,speed=40)
      was=pulse.pressing
      b=pulse.update(tick*.01,counter,main_pressed=tick<2,manual_button=0,blocked=False,
                     request=True,stock_enabled=stock,configured=True)
      if b is not None:
        self.assertTrue(lib.safety_tx_hook(packet(0x4f1,data(0x4f1,button=b,counter=counter+1))),(tick,b))
        if b==2 and not was:
          starts.append(tick)
    self.assertEqual(starts,[52,164])
    self.assertEqual(pulse.acks,1)

  def test_startup_keeps_speed_retry_timing_independent_under_native_guards(self):
    from opendbc.car.hyundai.porter import PorterCruiseButtons
    from opendbc.car.hyundai.porter_main_set import PorterMainSet
    init(9217)
    startup, speed = PorterMainSet(), PorterCruiseButtons()
    requests = []
    for tick in range(850):
      lib.set_timer(21000+tick*10000)
      counter, stock = tick//2, tick>=168
      if tick % 2 == 0:
        seed(counter=counter, main=tick==0, target=40 if stock else 0, speed=40)
      before = speed.requests
      button = speed.update(tick*.01, 45, 40, counter, enabled=stock)
      if speed.requests != before:
        requests.append((tick*.01, speed.request_sample_delay))
      main_button = startup.update(tick*.01, counter, main_pressed=tick<2, manual_button=0,
                                   blocked=False, request=not stock, stock_enabled=stock, configured=True)
      if button is None:
        button = main_button
      if button is not None:
        self.assertTrue(lib.safety_tx_hook(packet(0x4f1, data(0x4f1, button=button, counter=counter+1))),
                        (tick, button))
    self.assertEqual([slot for _, slot in requests[:4]], [0., .01, 0., .01])
    self.assertGreaterEqual(requests[1][0]-requests[0][0], 1.)
    self.assertGreaterEqual(requests[2][0]-requests[1][0], 1.)
    self.assertGreaterEqual(requests[3][0]-requests[2][0], 3.5)
    self.assertEqual(speed.preferred_sample_delay, 0.)  # startup and misses do not teach a speed ACK

  def test_immediate_release_after_brake_or_cancel_passes_native(self):
    from opendbc.car.hyundai.porter_main_set import PorterMainSet
    for override in ('brake', 'cancel'):
      init(9217)
      pulse = PorterMainSet()
      starts = []
      for tick in range(280):
        counter, stock = tick//2, 105 <= tick < 200
        gas = tick < 100 or 230 <= tick < 260
        brake = override == 'brake' and 200 <= tick < 220
        manual = 4 if override == 'cancel' and 200 <= tick < 220 else 0
        lib.set_timer(21000+tick*10000)
        if tick % 2 == 0:
          seed(counter=counter, main=tick==0, target=40 if stock else 0, speed=40,
               gas=gas, brake=brake, button=manual)
        was = pulse.pressing
        button = pulse.update(tick*.01, counter, main_pressed=tick<2, manual_button=manual,
                              blocked=brake, request=not gas, stock_enabled=stock,
                              configured=True, gas_pressed=gas)
        if button is not None:
          self.assertTrue(lib.safety_tx_hook(packet(0x4f1, data(0x4f1, button=button, counter=counter+1))),
                          (override, tick, button))
          if button == 2 and not was:
            starts.append(tick)
      self.assertEqual(starts, [100, 260])  # both release edges, no confirmation dwell

  def test_interrupted_immediate_release_attempts_keep_native_retry_backoff(self):
    from opendbc.car.hyundai.porter_main_set import PorterMainSet
    init(9217)
    pulse = PorterMainSet()
    starts = []
    for tick in range(601):
      counter = tick//2
      gas = tick < 100 or tick % 100 in (2, 3)
      lib.set_timer(21000+tick*10000)
      if tick % 2 == 0:
        seed(counter=counter, main=tick==0, speed=40, gas=gas)
      was = pulse.pressing
      button = pulse.update(tick*.01, counter, main_pressed=tick<2, manual_button=0, blocked=False,
                            request=not gas, stock_enabled=False, configured=True, gas_pressed=gas)
      if button is not None:
        self.assertTrue(lib.safety_tx_hook(packet(0x4f1, data(0x4f1, button=button, counter=counter+1))),
                        (tick, button))
        if button == 2 and not was:
          starts.append(tick)
    self.assertEqual(starts, [100, 200, 300, 600])

  def test_off_set_transport_window_keeps_latest_counter_guard(self):
    # CAN batches are published after physical RX; TX also takes transport time.
    # These offsets are a regression scenario, not measured vehicle latencies.
    from opendbc.car.hyundai.porter_main_set import PorterMainSet
    for extra_delay in (0., .01):
      init(9217)
      pulse = PorterMainSet()
      next_rx = 0
      rejected = []
      sent_set = 0

      def receive_until(now):
        nonlocal next_rx
        while next_rx * .02 - .006 <= now + 1e-9:
          lib.set_timer(round((.021 + next_rx * .02 - .006) * 1e6))
          seed(counter=next_rx, main=next_rx==0, speed=40)
          next_rx += 1

      for tick in range(180):
        now = tick * .01
        receive_until(now)
        button = pulse.update(now, tick//2, main_pressed=tick<2, manual_button=0, blocked=False,
                              request=True, stock_enabled=False, configured=True)
        if button is not None:
          delivery = now + .005 + extra_delay
          receive_until(delivery)
          lib.set_timer(round((.021 + delivery) * 1e6))
          allowed = lib.safety_tx_hook(packet(0x4f1,data(0x4f1,button=button,counter=tick//2+1)))
          if button == 2:
            sent_set += 1
            if not allowed:
              rejected.append(tick)
      self.assertGreater(sent_set, 6)
      if extra_delay:
        self.assertTrue(rejected)  # stale delayed packets remain forbidden
      else:
        self.assertEqual(rejected, [])

  def test_cluster_profile_can_set_at_dashboard31_and_wheels29(self):
    self.startup_pedal(param=60417, speed=29, cluster_speed=31.5)
    self.assertTrue(lib.safety_config_valid())
    self.assertTrue(self.tx(counter=46))
    self.assertFalse(lib.get_controls_allowed())
    self.startup_pedal(param=58369, speed=29, cluster_speed=31.5)
    self.assertFalse(self.tx(counter=46))  # old raw-wheel floor is unchanged

  def test_cluster_profile_requires_speed_bounds_both_wheels_and_metric(self):
    for args in (dict(speed=29, cluster_speed=29.875), dict(speed=160, cluster_speed=160.125),
                 dict(speed=24.96875, cluster_speed=30), dict(speed=25, cluster_speed=30.125),
                 dict(speed=29, speed_rr=24, cluster_speed=31.5),
                 dict(speed=29, speed_fl=24, cluster_speed=31.5),
                 dict(speed=29, cluster_speed=31.5, cluster_metric=False),
                 dict(speed=0, cluster_speed=30), dict(speed=161, cluster_speed=160)):
      self.startup_pedal(param=60417, **args)
      self.assertFalse(self.tx(counter=46), args)
    for args in (dict(speed=25, cluster_speed=30), dict(speed=160, cluster_speed=160),
                 dict(speed=29, cluster_speed=31.375)):
      self.startup_pedal(param=60417, **args)
      self.assertTrue(self.tx(counter=46), args)

  def test_cluster_profile_cannot_bypass_overrides_stale_rx_or_counter(self):
    for guard in (dict(brake=True), dict(gas=True), dict(hold=True), dict(park=True),
                  dict(drive=False), dict(main=True), dict(button=4)):
      self.startup_pedal(param=60417, speed=29, cluster_speed=31.5, **guard)
      self.assertFalse(self.tx(counter=46), guard)
    self.startup_pedal(param=60417, speed=29, cluster_speed=31.5)
    self.assertFalse(self.tx(counter=45))  # same latest-counter+1 rule
    lib.set_timer(1041001)
    self.assertFalse(self.tx(counter=46))  # stale inputs / expired one-shot

  def test_cluster_profile_physical_main_mode_and_bounded_unknown_startup(self):
    self.prepare(param=11265)
    lib.set_timer(701000)
    seed(counter=35, speed=29, cluster_speed=31.5)
    self.assertTrue(self.tx(counter=36))
    self.assertFalse(self.tx(counter=36))
    self.startup_pedal(param=60417, speed=29, cluster_speed=31.5)
    for i in range(6):
      if i:
        lib.set_timer(921000+i*20000)
        seed(counter=45+i, speed=29, cluster_speed=31.5)
      self.assertTrue(self.tx(counter=46+i))
    lib.set_timer(1041000)
    seed(counter=51, speed=29, cluster_speed=31.5)
    self.assertFalse(self.tx(counter=52))

  def test_cluster_profile_host_and_native_share_release_eligibility(self):
    from types import SimpleNamespace as NS
    from opendbc.car.hyundai.porter import porter_auto_set_speed_valid
    from opendbc.car.hyundai.porter_main_set import PorterMainSet
    init(60417)
    pulse = PorterMainSet(initial_main=True, allow_startup_gas=True)
    cp = NS(safetyConfigs=[NS(safetyParam=60417)])
    cs = NS(vEgo=29/3.6, vEgoCluster=31.5/3.6, wheelSpeeds=NS(fl=29/3.6, rr=29/3.6))
    output = []
    for tick in range(300):
      counter, gas = tick//2, 20<=tick<100
      lib.set_timer(21000+tick*10000)
      if tick % 2 == 0:
        seed(counter=counter, speed=29, cluster_speed=31.5, gas=gas)
      button = pulse.update(tick*.01, counter, main_pressed=False, manual_button=0, blocked=False,
                            request=not gas and porter_auto_set_speed_valid(cp, cs),
                            stock_enabled=False, configured=True, gas_pressed=gas)
      if button is not None:
        self.assertTrue(lib.safety_tx_hook(packet(0x4f1, data(0x4f1, speed=29, cluster_speed=31.5,
                                                          counter=counter+1, button=button))), (tick,button))
        output.append(button)
    self.assertEqual(output, [2]*6+[0])
    self.assertFalse(lib.get_controls_allowed())
