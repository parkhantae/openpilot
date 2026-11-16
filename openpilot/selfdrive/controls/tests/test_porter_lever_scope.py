"""A CAN-FD-only lever setting must not overwrite Classic Porter turn intent."""
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from openpilot.cereal import log
from openpilot.selfdrive.controls.lib.desire_helper import DesireHelper


def helper(supported):
  params = SimpleNamespace(get_int=lambda key: 5 if key == 'BlinkerLatchedTurn' else 0,
                           get_float=lambda key: 0., get_bool=lambda key: key == 'LaneChangeLeverWait')
  with patch('openpilot.selfdrive.controls.lib.desire_helper.Params', return_value=params), \
       patch('openpilot.selfdrive.controls.lib.desire_helper.CommandReader') as reader:
    reader.return_value.read.return_value = None
    h = DesireHelper(blinker_lever_supported=supported, turn_completion_guard=True)
  h.frame = 100
  h._update_params_periodic()
  h._update_params_periodic = lambda: None
  h._process_sides = lambda *_: None
  h._check_desire_state = lambda *_: None
  h.maneuver_type = 'lane_change'
  h.atc_type = 'atc right'
  for side in (h.left, h.right):
    side.lane_available = True
    side.edge_available = False
    side.lane_exist_count.counter = 10
    side.dist_to_edge_far = 1.5
  return h


@pytest.mark.parametrize('supported', [False, True])
def test_saved_lever_options_require_supported_input(supported):
  h = helper(supported)
  assert h.blinkerLatchedTurn == (5 / 3.6 if supported else 0.)
  assert h.laneChangeLeverWait is supported


@pytest.mark.parametrize('direction', ['left', 'right'])
@pytest.mark.parametrize('supported', [False, True])
def test_low_speed_atc_turn_keeps_geometry_gate_without_porter_lever_override(direction, supported):
  h = helper(supported)
  h.atc_type = 'atc ' + direction
  car = SimpleNamespace(canValid=True, vEgo=25/3.6, aEgo=0., trailerConnected=False,
                        leftBlinker=direction == 'left', rightBlinker=direction == 'right',
                        steeringAngleDeg=0., steeringPressed=False, steeringTorque=0.,
                        blinkerLever=0, blinkerLamp=0, leftBlinkerStalkCount=0, rightBlinkerStalkCount=0)
  nav = SimpleNamespace(atcType='turn ' + direction, carrotCmdIndex=0, carrotCmd='', carrotArg='')
  side = h.left if direction == 'left' else h.right
  h.update(car, SimpleNamespace(), True, .5, nav, SimpleNamespace())
  assert h.desire == log.Desire.none  # An ATC cue alone does not waive the road-edge gate.
  side.dist_to_edge_far = 5.
  h.update(car, SimpleNamespace(), True, .5, nav, SimpleNamespace())
  assert h.desire == (log.Desire.none if supported else
                       log.Desire.turnLeft if direction == 'left' else log.Desire.turnRight)
  assert not h.lever_turn


@pytest.mark.parametrize('fingerprint,supported', [('HYUNDAI_PORTER_II_EV', False), ('HYUNDAI_IONIQ_5', True), ('HYUNDAI_IONIQ_5_PE', True)])
def test_modeld_passes_porter_capability_to_real_helper(fingerprint, supported):
  modeld = Path(__file__).parents[2] / 'modeld' / 'modeld.py'
  calls = [n for n in ast.walk(ast.parse(modeld.read_text())) if isinstance(n, ast.Call)
           and isinstance(n.func, ast.Name) and n.func.id == 'DesireHelper']
  assert len(calls) == 1
  keyword = next(k for k in calls[0].keywords if k.arg == 'blinker_lever_supported')
  value = eval(compile(ast.Expression(keyword.value), str(modeld), 'eval'),
               {'CP': SimpleNamespace(carFingerprint=fingerprint)})
  assert value is supported
