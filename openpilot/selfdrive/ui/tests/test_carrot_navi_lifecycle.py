import ast
from pathlib import Path
from types import SimpleNamespace


ROAD_VIEW = Path(__file__).parents[1] / "onroad" / "augmented_road_view.py"


def road_view(onroad):
  tree = ast.parse(ROAD_VIEW.read_text())
  original = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "AugmentedRoadView")
  methods = [n for n in original.body if isinstance(n, ast.FunctionDef)
             and n.name in ("_offroad_transition", "set_cluster_hud_connected")]

  class CameraView:
    def _offroad_transition(self):
      self.base_transitions += 1

  class Map:
    def close(self):
      closed.append(True)

  closed = []
  state = SimpleNamespace(is_onroad=lambda: onroad)
  cls = ast.ClassDef(name="AugmentedRoadView", bases=[ast.Name(id="CameraView", ctx=ast.Load())],
                     keywords=[], body=methods, decorator_list=[])
  namespace = {"CameraView": CameraView, "ui_state": state}
  exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])), "actual_road_map_lifecycle", "exec"), namespace)
  view = namespace["AugmentedRoadView"]()
  view.base_transitions = 0
  view._carrot_navi_map = Map()
  view._suppress_camera_for_cluster = False
  return view, closed


def test_leaving_onroad_releases_map_and_preserves_base_transition():
  view, closed = road_view(False)
  view._offroad_transition()
  assert view.base_transitions == 1
  assert len(closed) == 1


def test_entering_onroad_keeps_new_map_resources_available():
  view, closed = road_view(True)
  view._offroad_transition()
  assert view.base_transitions == 1
  assert closed == []


def test_hiding_road_view_for_cluster_releases_map_once():
  view, closed = road_view(True)
  view.set_cluster_hud_connected(True, False)
  assert view._suppress_camera_for_cluster is True
  assert len(closed) == 1
  view.set_cluster_hud_connected(True, False)
  assert len(closed) == 1
  view.set_cluster_hud_connected(True, True)
  assert view._suppress_camera_for_cluster is False
  assert len(closed) == 1
