import unittest
from types import SimpleNamespace as NS

from opendbc.car.hyundai.porter_main_set import PorterMainSet
from opendbc.car.hyundai.porter import porter_auto_set_speed_valid, supports_porter_button_cruise


class TestPorterSetPair(unittest.TestCase):
  def test_pair_profile_retains_shared_porter_and_wheel_admission(self):
    cp = NS(brand='hyundai', carFingerprint='HYUNDAI_PORTER_II_EV', pcmCruise=True,
            openpilotLongitudinalControl=False, safetyConfigs=[NS(safetyModel='hyundai', safetyParam=15361)])
    cs = NS(vEgo=29/3.6, vEgoCluster=31.5/3.6, wheelSpeeds=NS(fl=29/3.6, rr=29/3.6))
    self.assertTrue(supports_porter_button_cruise(cp))
    self.assertTrue(porter_auto_set_speed_valid(cp, cs))

  def setUp(self):
    self.state = PorterMainSet(two_press=True)

  def tick(self, tick, **overrides):
    args = dict(main_pressed=tick < 2, manual_button=0, blocked=False,
                request=not 20 <= tick < 100, stock_enabled=False, configured=True,
                gas_pressed=20 <= tick < 100)
    args.update(overrides)
    return self.state.update(tick * .01, tick // 2, **args)

  def run_pair(self, **overrides):
    starts, outputs = [], []
    for tick in range(900):
      before = self.state.requests
      args = {key: value(tick) for key, value in overrides.items()}
      button = self.tick(tick, **args)
      if self.state.requests != before:
        starts.append(tick)
      if button is not None:
        outputs.append((tick, button))
    return starts, outputs

  def test_one_release_sends_at_most_two_complete_presses_then_stops(self):
    starts, outputs = self.run_pair()
    self.assertEqual(starts, [100, 114])
    self.assertEqual(outputs[:4], [(100, 2), (102, 2), (104, 2), (106, 0)])
    self.assertEqual(outputs[4:], [(114, 2), (116, 2), (118, 2), (120, 0)])
    self.assertEqual(self.state.pair_index, 2)
    self.assertEqual(self.state.pair_remaining, 0)

  def test_first_success_still_completes_both_presses(self):
    starts, outputs = self.run_pair(stock_enabled=lambda t:t >= 103)
    self.assertEqual(starts, [100, 114])
    self.assertEqual(outputs, [(100, 2), (102, 2), (104, 2), (106, 0),
                               (114, 2), (116, 2), (118, 2), (120, 0)])
    self.assertEqual(self.state.acks, 1)
    self.assertEqual(self.state.timeouts, 0)

  def test_stock_on_just_before_second_does_not_cancel_pair(self):
    starts, _ = self.run_pair(stock_enabled=lambda t:t >= 113)
    self.assertEqual(starts, [100, 114])
    self.assertEqual(self.state.acks, 1)

  def test_each_driver_or_input_interruption_discards_remaining_press(self):
    for key, value in (('blocked', True), ('manual_button', 4), ('main_pressed', True),
                       ('configured', False), ('request', False), ('release_eligible', False)):
      with self.subTest(key=key):
        self.setUp()
        starts, _ = self.run_pair(**{key:lambda t,v=value,k=key:v if 108 <= t < 110 else
                                    (0 if k == 'manual_button' else
                                     t < 2 if k == 'main_pressed' else
                                     not 20 <= t < 100 if k == 'request' else
                                     k in ('configured', 'release_eligible'))})
        self.assertEqual(starts, [100])
        self.assertEqual(self.state.pair_remaining, 0)

  def test_new_gas_press_cancels_old_pair_and_blocked_release_is_not_queued(self):
    starts, _ = self.run_pair(gas_pressed=lambda t:20 <= t < 100 or 108 <= t < 130,
                              request=lambda t:not (20 <= t < 100 or 108 <= t < 130))
    self.assertEqual(starts, [100])

  def test_abandoned_pair_after_first_ack_still_reserves_native_quiet_period(self):
    starts, _ = self.run_pair(stock_enabled=lambda t:103 <= t < 110,
                              configured=lambda t:not 108 <= t < 110,
                              gas_pressed=lambda t:20 <= t < 100 or 130 <= t < 150,
                              request=lambda t:not (20 <= t < 100 or 130 <= t < 150))
    self.assertEqual(starts, [100])
    self.assertEqual(self.state.acks, 1)

  def test_second_is_available_with_both_controls_inactive(self):
    starts, _ = self.run_pair(pedal_only=lambda t:True)
    self.assertEqual(starts, [100, 114])

  def test_no_pedal_never_starts_even_if_main_and_lateral_are_ready(self):
    starts, _ = self.run_pair(gas_pressed=lambda t:False, request=lambda t:True,
                              pedal_only=lambda t:False)
    self.assertEqual(starts, [])

  def test_main_off_never_starts_from_pedal_alone(self):
    starts, _ = self.run_pair(main_pressed=lambda t:False)
    self.assertEqual(starts, [])

  def test_pair_expiry_cannot_be_renewed_by_waiting_for_a_fresh_sample(self):
    for tick in range(110):
      self.tick(tick)
    self.state.next_request = 5.
    starts = []
    for tick in range(110, 900):
      before = self.state.requests
      self.tick(tick)
      if self.state.requests != before:
        starts.append(tick)
    self.assertEqual(starts, [])

  def test_pair_mode_requires_confirmed_main(self):
    self.state = PorterMainSet(initial_main=True, allow_startup_gas=True, two_press=True)
    starts, _ = self.run_pair(main_pressed=lambda t:False)
    self.assertEqual(starts, [])
    self.assertFalse(self.state.main_known)

  def test_new_qualified_pedal_cycle_can_start_another_pair(self):
    starts, outputs = self.run_pair(gas_pressed=lambda t:20 <= t < 100 or 760 <= t < 800,
                                    request=lambda t:not (20 <= t < 100 or 760 <= t < 800))
    self.assertEqual(starts, [100, 114, 801, 815])
    self.assertEqual(outputs[-8:], [(801, 2), (803, 2), (805, 2), (806, 0),
                                    (815, 2), (817, 2), (819, 2), (820, 0)])

  def test_unanswered_pair_tries_delayed_slot_and_ack_remembers_it(self):
    starts, outputs = [], []
    for tick in range(900):
      gas = 20 <= tick < 100 or 760 <= tick < 800
      before = self.state.requests
      button = self.tick(tick, gas_pressed=gas, request=not gas, stock_enabled=tick >= 803)
      if self.state.requests != before:
        starts.append(tick)
      if button is not None:
        outputs.append((tick, button))

    self.assertEqual(starts, [100, 114, 801, 815])
    self.assertEqual(outputs[-8:], [(801, 2), (803, 2), (805, 2), (806, 0),
                                    (815, 2), (817, 2), (819, 2), (820, 0)])
    self.assertEqual(self.state.acks, 1)
    self.assertEqual(self.state.preferred_sample_delay, .01)
    self.assertEqual(self.state.retry_sample_delay, .01)
