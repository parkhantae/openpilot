from types import SimpleNamespace as NS

import pytest

from openpilot.cereal import car, log
from openpilot.selfdrive.controls.lib.desire_helper import DesireHelper
from openpilot.selfdrive.controls.lib.desire_lib.turn_completion import NavigationTurnCompletion


def fixture(guard=True, right=True):
  with pytest.MonkeyPatch.context() as patcher:
    patcher.setattr('openpilot.selfdrive.controls.lib.desire_helper.Params', lambda: NS())
    patcher.setattr('openpilot.selfdrive.controls.lib.desire_helper.CommandReader', lambda *_: NS(read=lambda **_: None))
    dh = DesireHelper(turn_completion_guard=guard)
  dh._update_params_periodic = lambda: None
  dh._process_sides = lambda *_: None
  for side in (dh.left, dh.right):
    side.dist_to_edge_far = 6.0
  state = car.CarState.new_message(canValid=True, vEgo=5.0, gearShifter='drive')
  model = log.ModelDataV2.new_message()
  model.orientationRate.z = [0.35] * 15 + [0.31]
  model.meta.desireState = [0.0, 0.0 if right else 1.0, 1.0 if right else 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
  nav = NS(atcType='turn right' if right else 'turn left', carrotCmdIndex=0, carrotCmd='', carrotArg='')

  def step(angle, *, active=True, valid=True):
    state.steeringAngleDeg = angle
    return dh.update(state, model, active, 0.1, nav, NS(), turn_input_valid=valid)

  return dh, state, model, nav, step


@pytest.mark.parametrize('right', [False, True])
def test_recorded_peak_yaw_does_not_end_an_unfinished_navigation_turn(right):
  dh, state, _, nav, step = fixture(right=right)
  sign = -1 if right else 1
  expected = log.Desire.turnRight if right else log.Desire.turnLeft
  step(sign * 62)
  assert step(sign * 62) == expected
  # Measured steering is still 208deg when predicted future yaw falls.
  for angle in (99, 173, 198, 208, 217, 226, 265, 231, 149, 104):
    assert step(sign * angle) == expected
    assert dh.turn_disable_count == 0
  assert dh.navigation_turn.peak == 265
  nav.atcType = 'none'
  assert step(sign * 104) == log.Desire.none
  state.latEnabled = False


def test_legacy_unrelated_profile_retains_existing_yaw_decay_rule():
  dh, _, _, _, step = fixture(guard=False)
  step(-62)
  assert step(-62) == log.Desire.turnRight
  assert step(-208) == log.Desire.none
  assert dh.turn_disable_count > 0


@pytest.mark.parametrize('right', [False, True])
def test_measured_return_finishes_turn_without_rearming_from_same_cue(right):
  _, _, _, _, step = fixture(right=right)
  sign = -1 if right else 1
  step(sign * 20)
  step(sign * 90)
  step(sign * 210)
  for _ in range(3):
    assert step(sign * 14) != log.Desire.none
  assert step(sign * 14) == log.Desire.none
  for _ in range(20):
    assert step(sign * 14) == log.Desire.none


@pytest.mark.parametrize('reason', ['inactive', 'opposite_blinker', 'trailer', 'invalid_can', 'invalid_angle'])
def test_existing_abort_conditions_still_stop_guarded_turn(reason):
  dh, state, _, _, step = fixture()
  step(-62)
  step(-120)
  if reason == 'opposite_blinker':
    state.leftBlinker = True
  if reason == 'trailer':
    state.trailerConnected = True
  if reason == 'invalid_can':
    state.canValid = False
  result = step(float('nan') if reason == 'invalid_angle' else -208, active=reason != 'inactive')
  # The opposite physical stalk cancels navigation and remains a driver request.
  assert result == (log.Desire.turnLeft if reason == 'opposite_blinker' else log.Desire.none)
  if reason == 'inactive':
    assert dh.maneuver_type == 'none'


def test_stationary_wheel_does_not_count_as_completed_turn():
  t = NavigationTurnCompletion()
  t.update(2, -200, True)
  for _ in range(1000):
    assert not t.update(2, 0.0, False)
  for _ in range(4):
    done = t.update(2, 14.0, True)
  assert done


def test_navigation_completion_does_not_block_a_new_opposite_driver_request():
  dh, state, _, _, step = fixture()
  step(-20)
  step(-90)
  step(-210)
  for _ in range(4):
    step(-14)
  assert dh.navigation_turn.finished
  state.leftBlinker = True
  assert step(0) == log.Desire.turnLeft
  assert dh.atc_active == 2


def test_invalid_or_stale_planner_inputs_cannot_start_or_retain_navigation_turn():
  _, _, _, _, step = fixture()
  for _ in range(5):
    assert step(-62, valid=False) == log.Desire.none
  step(-62)
  assert step(-62) == log.Desire.turnRight
  assert step(-208, valid=False) == log.Desire.none


def test_unchanged_stale_turn_cue_has_a_bounded_execution_window():
  t = NavigationTurnCompletion()
  for _ in range(199):
    assert not t.update(2, -200.0, True)
  for _ in range(2):
    done = t.update(2, -200.0, True)
  assert done
  assert t.update(2, -200.0, True)
  assert not t.update(1, 100.0, True)


def test_return_must_be_continuous_and_invalid_angle_cannot_extend_turn():
  t = NavigationTurnCompletion()
  t.update(2, -200.0, True)
  for _ in range(3):
    assert not t.update(2, -14.0, True)
  assert not t.update(2, -40.0, True)
  for _ in range(3):
    assert not t.update(2, -14.0, True)
  assert t.update(2, float('nan'), True)


@pytest.mark.parametrize('right', [False, True])
def test_manual_countersteer_past_straight_aborts_without_a_return_dwell(right):
  direction, sign = (2, -1) if right else (1, 1)
  t = NavigationTurnCompletion()
  t.update(direction, sign * 100., True)
  # Assistance in the turn direction is not an abort, nor is opposite torque
  # alone before measured wheel return. These can occur during an unfinished turn.
  assert not t.update(direction, sign * 150., True, driver_pressed=True, driver_torque=sign * 300.)
  assert not t.update(direction, sign * 90., True, driver_pressed=True, driver_torque=-sign * 300.)
  assert not t.update(direction, sign * 8., True, driver_pressed=True, driver_torque=-sign * 300.)
  assert t.update(direction, -sign * 16., True, driver_pressed=True, driver_torque=-sign * 300.)
  assert t.aborted


@pytest.mark.parametrize('pressed,torque,moving', [(False, -300., True), (True, 300., True),
                                                (True, -300., False), (True, float('nan'), True)])
def test_opposite_angle_requires_opposing_manual_input_and_motion(pressed, torque, moving):
  t = NavigationTurnCompletion()
  t.update(1, 100., True)
  assert not t.update(1, -30., moving, driver_pressed=pressed, driver_torque=torque)
  assert not t.aborted


def test_recorded_aborted_left_does_not_rearm_from_passed_cue_but_allows_next_right():
  dh, state, _, nav, step = fixture(right=False)
  nav.xDistToTurn = 14
  step(81.)
  step(99.)
  assert step(99.) == log.Desire.turnLeft
  state.steeringPressed, state.steeringTorque = True, -300.
  step(8.)
  assert step(-30.) == log.Desire.none
  assert dh.aborted_navigation_turns == {1}
  # Current cue still ahead by a few metres must not erase the driver's abort.
  for _ in range(10):
    assert step(-80.) == log.Desire.none
  state.steeringPressed, state.steeringTorque = False, 0.
  nav.atcType, nav.xDistToTurn = 'turn right prepare', 346
  step(0.)
  nav.atcType, nav.xDistToTurn = 'turn left', -1
  for _ in range(20):
    assert step(27.) == log.Desire.none
  nav.atcType, nav.xDistToTurn = 'none', 0
  step(0.)
  nav.atcType, nav.xDistToTurn = 'turn right', 32
  step(-16.)
  assert step(-60.) == log.Desire.turnRight


@pytest.mark.parametrize('fresh', [False, True])
def test_same_direction_rearm_needs_fresh_preparation_and_positive_current_distance(fresh):
  dh, state, _, nav, step = fixture(right=False)
  nav.xDistToTurn = 5
  step(99.)
  step(99.)
  step(99.)
  state.steeringPressed, state.steeringTorque = True, -300.
  assert step(-30.) == log.Desire.none
  state.steeringPressed, state.steeringTorque = False, 0.
  nav.atcType, nav.xDistToTurn = 'turn left prepare', 100
  step(0., valid=fresh)
  nav.atcType, nav.xDistToTurn = 'turn left', -1
  step(0.)
  assert step(0.) == log.Desire.none
  nav.xDistToTurn = 20
  result = step(0.)
  assert result == (log.Desire.turnLeft if fresh else log.Desire.none)
  assert (not dh.aborted_navigation_turns) == fresh


def test_manual_stalk_and_new_lateral_session_remain_available_after_abort():
  dh, state, _, nav, step = fixture(right=False)
  nav.xDistToTurn = 5
  step(99.)
  step(99.)
  step(99.)
  state.steeringPressed, state.steeringTorque = True, -300.
  assert step(-30.) == log.Desire.none
  state.steeringPressed, state.steeringTorque = False, 0.
  state.leftBlinker = True
  assert step(0.) == log.Desire.turnLeft
  state.leftBlinker = False
  step(0., active=False)
  assert not dh.aborted_navigation_turns
  step(20.)
  assert step(20.) == log.Desire.turnLeft


def test_invalid_manual_sample_stops_turn_without_latching_a_driver_abort():
  dh, state, _, _, step = fixture(right=False)
  for _ in range(3):
    step(99.)
  state.steeringPressed, state.steeringTorque = True, -300.
  assert step(-30., valid=False) == log.Desire.none
  assert not dh.aborted_navigation_turns


def test_opposite_abort_does_not_forget_a_previous_aborted_direction():
  dh, state, _, nav, step = fixture(right=False)
  nav.xDistToTurn = 5
  for _ in range(3):
    step(99.)
  state.steeringPressed, state.steeringTorque = True, -300.
  assert step(-30.) == log.Desire.none
  state.steeringPressed, state.steeringTorque = False, 0.
  nav.atcType, nav.xDistToTurn = 'turn right', 32
  for _ in range(3):
    step(-99.)
  state.steeringPressed, state.steeringTorque = True, 300.
  assert step(30.) == log.Desire.none
  assert dh.aborted_navigation_turns == {1, 2}
  state.steeringPressed, state.steeringTorque = False, 0.
  for cue in ('turn left', 'turn right'):
    nav.atcType, nav.xDistToTurn = cue, -1
    for _ in range(5):
      assert step(0.) == log.Desire.none
