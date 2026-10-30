"""Real gesture batches and the production HUD selection/storage path."""
import ast
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from openpilot.selfdrive.ui.onroad.gap_touch import GapTouch
from openpilot.selfdrive.ui.tests import test_carrot_hud_renderer as hud_tests


hud_module = hud_tests.hud_module
FakeParams = hud_tests.FakeParams


def event(x=10, y=10, t=1.0, *, press=False, release=False, slot=0):
  return NS(pos=NS(x=x, y=y), t=t, slot=slot, left_pressed=press, left_released=release,
            left_down=not release)


def test_short_tap_fires_only_on_release_and_once():
  calls = []
  touch = GapTouch(lambda: calls.append(True))
  rect = NS(x=0, y=0, width=100, height=100)
  touch.update((rect,), [event(press=True)], enabled=True)
  assert not calls
  touch.update((rect,), [event(t=1.1, release=True)], enabled=True)
  touch.update((rect,), [event(t=1.2, release=True)], enabled=True)
  assert calls == [True]


@pytest.mark.parametrize('events', [
  [event(release=True)],
  [event(press=True), event(t=1.6, release=True)],
  [event(press=True), event(x=60, t=1.1), event(t=1.2, release=True)],
  [event(x=-1, press=True), event(t=1.1, release=True)],
  [event(press=True), event(x=101, t=1.1, release=True)],
  [event(press=True), event(t=0.9, release=True)],
  [event(press=True), event(t=float('nan'), release=True)],
  [event(press=True), event(slot=1, press=True), event(t=1.1, release=True)],
])
def test_hold_drag_outside_multitouch_or_bad_time_does_not_change_gap(events):
  calls = []
  touch = GapTouch(lambda: calls.append(True))
  touch.update((NS(x=0, y=0, width=100, height=100),), events, enabled=True)
  assert not calls


@pytest.mark.parametrize('disabled', [False, True])
def test_disable_or_layout_change_cancels_incomplete_tap(disabled):
  calls = []
  touch = GapTouch(lambda: calls.append(True))
  rect = NS(x=0, y=0, width=100, height=100)
  touch.update((rect,), [event(press=True)], enabled=True)
  if disabled:
    touch.update((rect,), [], enabled=False)
  else:
    rect.x = 1
  touch.update((rect,), [event(t=1.1, release=True)], enabled=True)
  assert not calls


def test_wake_touch_does_not_change_gap():
  calls = []
  touch = GapTouch(lambda: calls.append(True))
  rects = (NS(x=0, y=0, width=100, height=100),)
  touch.update(rects, [], enabled=True, awake=False)
  touch.update(rects, [event(press=True), event(t=1.1, release=True)], enabled=True, awake=True)
  assert not calls
  touch.update(rects, [event(t=2., press=True), event(t=2.1, release=True)], enabled=True, awake=True)
  assert calls == [True]


def hud_setup(hud_module, *, maximum=4, requested=4, direct_long=False, current=3):
  module, ui = hud_module
  ui.started = True
  ui.CP = NS(openpilotLongitudinalControl=direct_long)
  ui.params = FakeParams({'LongitudinalPersonalityMax': maximum, 'CruiseGapLevels': requested,
                          'LongitudinalPersonality': current})
  renderer = module.HudRenderer()
  return module, ui, renderer


def test_porter_cycles_four_three_two_one_without_touching_gap_values_or_modes(hud_module):
  _, ui, renderer = hud_setup(hud_module, requested=2)
  ui.params.values.update(PorterGapUse=1, PorterGap1=40, PorterAutoSetMain=0, ExperimentalMode=0)
  for expected in [2, 1, 0, 3, 2]:
    renderer._on_gap_tap()
    assert ui.params.values['LongitudinalPersonality'] == expected
    assert renderer._get_cruise_gap() == expected + 1
  assert ui.params.writes == [('LongitudinalPersonality', v) for v in [2, 1, 0, 3, 2]]
  assert {k: ui.params.values[k] for k in ['PorterGapUse', 'PorterGap1', 'PorterAutoSetMain', 'ExperimentalMode']} == {
    'PorterGapUse': 1, 'PorterGap1': 40, 'PorterAutoSetMain': 0, 'ExperimentalMode': 0,
  }


@pytest.mark.parametrize('maximum,requested,current,expected', [(3, 4, 0, 2), (4, 2, 0, 1), (4, 3, 3, 2)])
def test_direct_long_respects_supported_and_configured_gap_count(hud_module, maximum, requested, current, expected):
  _, ui, renderer = hud_setup(hud_module, maximum=maximum, requested=requested, direct_long=True, current=current)
  renderer._on_gap_tap()
  assert ui.params.values['LongitudinalPersonality'] == expected


def test_selection_persists_and_reaches_actual_selfdrived_personality_reader(hud_module, tmp_path):
  from openpilot.common.params import Params
  _, ui, renderer = hud_setup(hud_module)
  ui.params = Params(str(tmp_path / 'params'))
  ui.params.put_int('LongitudinalPersonalityMax', 4)
  ui.params.put_int('LongitudinalPersonality', 3)
  reader_path = Path(__file__).parents[2] / 'selfdrived/selfdrived.py'
  cls = next(n for n in ast.parse(reader_path.read_text()).body if isinstance(n, ast.ClassDef) and n.name == 'SelfdriveD')
  method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'read_personality_param')
  namespace = {}
  exec(compile(ast.Module(body=[method], type_ignores=[]), str(reader_path), 'exec'), namespace)
  for expected in [2, 1, 0, 3]:
    renderer._on_gap_tap()
    process = NS(params=Params(str(tmp_path / 'params')))
    assert namespace['read_personality_param'](process) == expected
    assert renderer._get_cruise_gap() == expected + 1


@pytest.mark.parametrize('blocked', ['offroad', 'hidden', 'no_car', 'read_failed', 'write_failed'])
def test_unavailable_or_failed_storage_never_changes_display_or_persists(hud_module, blocked):
  _, ui, renderer = hud_setup(hud_module)
  initial = renderer._get_cruise_gap()
  if blocked == 'offroad':
    ui.started = False
  elif blocked == 'hidden':
    renderer.is_cruise_available = False
  elif blocked == 'no_car':
    ui.CP = None
  elif blocked == 'read_failed':
    ui.params.failures['LongitudinalPersonality'] = 1
  else:
    def fail(*args):
      raise OSError('read-only test storage')
    ui.params.put_int = fail
  renderer._on_gap_tap()
  assert not ui.params.writes
  assert renderer._get_cruise_gap() == initial


def test_real_hud_render_consumes_fast_gap_taps_without_sidebar_or_hold_action(hud_module):
  module, ui, renderer = hud_setup(hud_module)
  renderer._refresh_hud_params = lambda now: None
  renderer._plot_renderer.update = lambda mode: None
  renderer._draw_cruise_speed_animation = lambda rect: None
  paint_keys = []
  renderer._overlay.draw = lambda rect, paint, key, **kw: paint_keys.append(key)
  rect = module.rl.Rectangle(20, 30, 1920, 1020)
  # Actual numeric label and bars inside the Carrot HUD's bottom-left block.
  number, bars = NS(x=380, y=880), NS(x=450, y=1000)
  source = Path(__file__).parents[1] / 'onroad/augmented_road_view.py'
  cls = next(n for n in ast.parse(source.read_text()).body if isinstance(n, ast.ClassDef) and n.name == 'AugmentedRoadView')
  method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_handle_mouse_press')
  namespace = {}
  exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), 'exec'), namespace)
  sidebar = []
  view = NS(_hud_renderer=renderer, _click_callback=lambda: sidebar.append(True))
  for index, pos in enumerate([number, bars]):
    module.gui_app.mouse_events = [event(pos.x, pos.y, 1 + index, press=True),
                                   event(pos.x, pos.y, 1.1 + index, release=True)]
    renderer._render(rect)
    namespace['_handle_mouse_press'](view, pos)
    assert not sidebar
    assert renderer._get_cruise_gap() == 3 - index
    assert paint_keys[-1][-1] == 2 - index
  assert not renderer._exp_button.is_pressed
  assert not renderer._gap_touch.contains(NS(x=465, y=860))  # Adjacent D/P/R/N gear box.
  namespace['_handle_mouse_press'](view, NS(x=1000, y=500))
  assert sidebar == [True]
