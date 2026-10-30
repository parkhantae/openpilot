"""Exercise the actual border painter with held CAN direction states."""
import ast
from collections import defaultdict
from functools import partial
from pathlib import Path
from types import SimpleNamespace as NS

import pytest


@pytest.fixture
def border():
  path = Path(__file__).parents[1] / 'onroad/augmented_road_view.py'
  cls = next(n for n in ast.parse(path.read_text()).body if isinstance(n, ast.ClassDef) and n.name == 'AugmentedRoadView')
  nodes = [n for n in cls.body if isinstance(n, ast.FunctionDef) and
           n.name in ('_blinker_display_state', '_draw_border_carrot')]
  draws, fallbacks = [], []
  clock = NS(now=10.0)
  cs = NS(steeringPressed=False, leftBlinker=False, rightBlinker=False, logCarrot='')

  class Messages(dict):
    alive = defaultdict(bool, carState=True)

  sm = Messages(carState=cs)
  rl = NS(Rectangle=lambda *args: args, ORANGE='orange', BLACK='black', WHITE='white',
          draw_rectangle=lambda *args: None, draw_rectangle_rounded=lambda rect, radius, count, color: draws.append(color),
          draw_rectangle_rounded_lines_ex=lambda *args: None)
  namespace = {'rl': rl, 'UI_BORDER_SIZE': 30, 'UIStatus': NS(OVERRIDE=0, ENGAGED=1, DISENGAGED=2),
               'time': NS(monotonic=lambda: clock.now), 'draw_text_ui_style': lambda *args, **kwargs: None,
               'ui_state': NS(sm=sm, lat_active=False, status=2)}
  exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), namespace)
  snapshot = NS(top_left='', top_left_op_long='', custom_sr=0., bottom_left='', bottom_right='')
  view = NS(_blinker_state=(False, False), _blinker_started_at=0.,
            _border_params=NS(refresh=lambda now: snapshot), _get_border_color=lambda status: 'blue',
            _draw_border=lambda rect: fallbacks.append(True))
  view._blinker_display_state = partial(namespace['_blinker_display_state'], view)

  def paint(now, left, right):
    clock.now, cs.leftBlinker, cs.rightBlinker = now, left, right
    draws.clear()
    namespace['_draw_border_carrot'](view, NS(x=0, y=0, width=2160, height=1080))
    return list(draws)

  return paint, sm, fallbacks


@pytest.mark.parametrize('left,right', [(True, False), (False, True), (True, True)])
def test_held_directions_blink_from_elapsed_time_with_synchronized_hazards(border, left, right):
  paint, _, _ = border
  on = ['orange' if left else 'black', 'orange' if right else 'black']
  assert paint(10., left, right) == on
  assert paint(10.2, left, right) == on
  assert paint(10.45, left, right) == ['black', 'black']
  assert paint(10.85, left, right) == on
  assert paint(11.25, left, right) == ['black', 'black']
  assert paint(11.3, False, False) == ['black', 'black']
  assert paint(11.35, left, right) == on


def test_direction_change_and_clock_reset_start_lit_without_lingering_other_side(border):
  paint, _, _ = border
  assert paint(10., True, False) == ['orange', 'black']
  assert paint(10.45, True, False) == ['black', 'black']
  assert paint(10.5, False, True) == ['black', 'orange']
  assert paint(1., False, True) == ['black', 'orange']


def test_missing_car_state_draws_only_the_existing_fallback_border(border):
  paint, sm, fallbacks = border
  sm.alive['carState'] = False
  assert paint(10., True, True) == []
  assert fallbacks == [True]
