"""A completed lane change needs a new confirmation, not a continuously held nudge."""
from types import SimpleNamespace

import pytest

from openpilot.cereal import log
from openpilot.common.realtime import DT_MDL
from openpilot.selfdrive.controls.tests.test_desire_helper_stalk import TestDesireHelperStalkRequest as StalkFixture

LCS = log.LaneChangeState


class TestNextLaneChangeConfirmation:
  @pytest.fixture(params=['left', 'right'], autouse=True)
  def setup(self, request):
    fixture = StalkFixture()
    fixture.setup_method()
    self.helper = fixture.helper
    self.direction = request.param
    self.side = self.helper.left if self.direction == 'left' else self.helper.right
    self.press_count = 0
    self.nav = SimpleNamespace(atcType='', carrotCmdIndex=0, carrotCmd='', carrotArg='')

  def step(self, *, pressed=True, torque=200., lamp=True, press=False, probability=0.):
    if press:
      self.press_count += 1
    left = self.direction == 'left'
    car = SimpleNamespace(canValid=True, leftBlinker=lamp and left, rightBlinker=lamp and not left,
                          vEgo=43/3.6, aEgo=0., trailerConnected=False,
                          steeringTorque=torque if left else -torque, steeringPressed=pressed,
                          blinkerLever=0, leftBlinkerStalkCount=self.press_count if left else 0,
                          rightBlinkerStalkCount=0 if left else self.press_count)
    self.helper.update(car, SimpleNamespace(), True, probability, self.nav, SimpleNamespace())
    return self.helper.lane_change_state

  def complete_with_held_torque(self, atc_type=''):
    self.step(lamp=False)
    assert self.step(probability=.5) == LCS.preLaneChange
    assert self.step(probability=.5) == LCS.laneChangeStarting
    self.nav.atcType = atc_type
    for _ in range(80):
      state = self.step()
      if state == LCS.preLaneChange:
        break
    assert state == LCS.preLaneChange and self.helper.next_lane_change

  def test_continuously_held_torque_does_not_request_another_lane(self):
    self.complete_with_held_torque()
    for _ in range(40):
      assert self.step() == LCS.preLaneChange

  def test_release_then_new_matching_nudge_permits_next_lane(self):
    self.complete_with_held_torque()
    for _ in range(round(.2 / DT_MDL)):
      assert self.step(pressed=False, torque=0.) == LCS.preLaneChange
    assert self.step() == LCS.laneChangeStarting

  def test_one_frame_pressed_dropout_is_not_a_new_confirmation(self):
    self.complete_with_held_torque()
    for _ in range(6):
      assert self.step(pressed=False, torque=0.) == LCS.preLaneChange
      assert self.step() == LCS.preLaneChange

  def test_new_stalk_press_still_requests_next_lane_without_releasing_torque(self):
    self.complete_with_held_torque()
    assert self.step(press=True) == LCS.laneChangeStarting

  def test_navigation_handoff_does_not_consume_the_previous_nudge(self):
    self.complete_with_held_torque(atc_type='atc ' + self.direction)
    for _ in range(10):
      assert self.step(lamp=False) == LCS.preLaneChange

  def test_geometry_release_cannot_bypass_the_new_confirmation(self):
    self.complete_with_held_torque()
    self.nav.atcType = 'atc ' + self.direction
    self.helper.laneLineCheck = 2
    self.side.lane_change_available_geom = False
    assert self.step() == LCS.preLaneChange

  def test_new_confirmation_retains_bsd_block(self):
    self.complete_with_held_torque()
    for _ in range(round(.2 / DT_MDL)):
      self.step(pressed=False, torque=0.)
    self.helper.laneChangeBsd = 1
    self.side.bsd_hold_counter = 2
    self.side.lane_change_available = False
    assert self.step() == LCS.preLaneChange

  def test_opposite_torque_cancels_while_waiting(self):
    self.complete_with_held_torque()
    assert self.step(torque=-200.) == LCS.off
    assert not self.helper.next_lane_change_torque_armed
