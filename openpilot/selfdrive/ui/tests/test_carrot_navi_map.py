from types import SimpleNamespace

import pytest
import pyray as rl

from openpilot.selfdrive.ui.onroad.carrot_navi_map import (
  CarrotNaviMapView,
  GeoPoint,
  ONROAD_H264_QUEUE_MAX,
  ONROAD_MAP_MEDIA_KEYS,
  RoadMapTexture,
  SimpleMapState,
  carrot_navi_panel_rect,
  colorize_map,
  map_state_from_carrot_navi,
  phone_map_hold_active,
  project_map_point,
  project_route,
  route_local_points,
)
from openpilot.selfdrive.ui.onroad.carrot_navi_stream import (
  NAVI_EXTERNAL_FRAGMENT_SHADER,
  NAVI_YUV_FRAGMENT_SHADER,
  NaviMapTextureRenderer,
  map_frame_from_dashboard,
)


def meta(present=True, sequence=1):
  return SimpleNamespace(present=present, sequence=sequence)


def carrot_navi_message(*, connected=True):
  return SimpleNamespace(
    schemaVersion=1,
    connected=connected,
    sessionId="test",
    vehicle=SimpleNamespace(
      meta=meta(), latitude=37.5, longitude=127.0, headingDeg=0.0, speedKph=30.0, roadName="",
    ),
    route=SimpleNamespace(
      meta=meta(), remainingDistanceM=500, remainingTimeSec=60,
      polyline=(
        SimpleNamespace(latitude=37.5, longitude=127.0),
        SimpleNamespace(latitude=37.5005, longitude=127.0),
        SimpleNamespace(latitude=37.5010, longitude=127.0003),
      ),
    ),
    navigationStatus=SimpleNamespace(meta=meta(False)),
    speed=SimpleNamespace(meta=meta(False)),
    guidanceCurrent=SimpleNamespace(meta=meta(False)),
    guidanceNext=SimpleNamespace(meta=meta(False)),
    trafficSignal=SimpleNamespace(meta=meta(False)),
    laneCurrent=SimpleNamespace(meta=meta(False)),
  )


def test_panel_matches_guidance_width_x_and_top_edge():
  panel = carrot_navi_panel_rect(rl.Rectangle(0, 0, 2160, 1080))

  assert panel.x == 1360
  assert panel.y == 10
  assert panel.width == 790
  assert panel.height == 760
  assert panel.y + panel.height == 1080 - 310


def test_map_state_requires_live_connected_vehicle_and_route():
  state = map_state_from_carrot_navi(carrot_navi_message(), True, True)

  assert state is not None
  assert state.vehicle == GeoPoint(37.5, 127.0)
  assert len(state.route) == 3
  assert map_state_from_carrot_navi(carrot_navi_message(), False, True) is None
  assert map_state_from_carrot_navi(carrot_navi_message(connected=False), True, True) is None


@pytest.mark.parametrize(
  ("heading", "point"),
  ((0.0, GeoPoint(37.501, 127.0)), (90.0, GeoPoint(37.5, 127.001))),
)
def test_route_is_rotated_heading_up(heading, point):
  state = SimpleMapState(GeoPoint(37.5, 127.0), heading, (GeoPoint(37.5, 127.0), point))
  local = route_local_points(state)

  assert local[-1].forward_m > 80
  assert local[-1].right_m == pytest.approx(0.0, abs=0.01)


def test_projected_route_uses_same_perspective_as_road_raster():
  state = map_state_from_carrot_navi(carrot_navi_message(), True, True)
  assert state is not None
  panel = rl.Rectangle(1360, 10, 790, 760)
  projected = project_route(route_local_points(state), panel)

  assert len(projected) == 3
  assert projected[0].x == pytest.approx(panel.x + panel.width / 2)
  assert projected[0].y == pytest.approx(panel.y + panel.height * 0.82)
  assert panel.y < projected[2].y < projected[1].y < projected[0].y


def test_distance_compression_fits_complete_map_into_mild_trapezoid():
  panel = rl.Rectangle(1360, 10, 790, 760)
  near_left = project_map_point(0, 192, panel)
  far_left = project_map_point(0, 0, panel)
  near_center = project_map_point(128, 192, panel)
  far_center = project_map_point(128, 0, panel)

  assert far_center.y < near_center.y
  assert far_left.x > near_left.x
  assert near_left.x == pytest.approx(panel.x)
  assert far_left.x == pytest.approx(panel.x + panel.width * 0.2)
  assert far_center.y == pytest.approx(panel.y)


def test_extra_perspective_only_changes_the_far_map():
  panel = rl.Rectangle(1360, 10, 790, 760)
  near = project_map_point(128, 180, panel)
  far = project_map_point(128, 80, panel)

  near_base_depth = (12 / (12 + 120)) / (192 / (192 + 120))
  near_base_y = panel.y + panel.height * 0.82 * (1 - near_base_depth)
  far_base_depth = (112 / (112 + 120)) / (192 / (192 + 120))
  far_base_y = panel.y + panel.height * 0.82 * (1 - far_base_depth)
  assert near.y == pytest.approx(near_base_y)
  assert far.y < far_base_y


def test_map_colorization_uses_aligned_raster_route_and_transparent_background():
  pixels = bytearray(256 * 256)
  pixels[1] = 128
  pixels[2] = 255
  rgba = colorize_map(bytes(pixels))

  assert tuple(rgba[0:4]) == (8, 14, 22, 45)
  assert tuple(rgba[4:8]) == (255, 110, 0, 255)
  assert tuple(rgba[8:11]) == (180, 194, 208)


def test_phone_map_requires_connected_fresh_render_stream():
  frame = SimpleNamespace(key="render:map_main", present=True)
  dashboard = SimpleNamespace(connected=True, map_stream_stalled=False, media=(frame,))

  assert map_frame_from_dashboard(dashboard) is frame
  dashboard.connected = False
  assert map_frame_from_dashboard(dashboard) is None
  dashboard.connected = True
  dashboard.map_stream_stalled = True
  assert map_frame_from_dashboard(dashboard) is None


def test_phone_map_holds_last_frame_across_short_stream_stall():
  assert phone_map_hold_active(100.0, 109.99)
  assert phone_map_hold_active(100.0, 110.0)
  assert not phone_map_hold_active(100.0, 110.01)
  assert not phone_map_hold_active(0.0, 1.0)


def test_phone_map_never_falls_back_to_simplified_map_while_connected():
  assert phone_map_hold_active(100.0, 1_000.0, connected=True)
  assert not phone_map_hold_active(100.0, 1_000.0, connected=False)
  assert not phone_map_hold_active(100.0, 99.0, connected=True)


def test_yuv_stream_samples_visible_stride_without_changing_map_colors():
  assert "vec2 mapCoord = fragTexCoord" in NAVI_YUV_FRAGMENT_SHADER
  assert "textureScaleX" not in NAVI_YUV_FRAGMENT_SHADER
  assert "gl_FragColor = vec4(clamp(rgb, 0.0, 1.0), 1.0)" in NAVI_YUV_FRAGMENT_SHADER


@pytest.mark.parametrize("shader", (NAVI_YUV_FRAGMENT_SHADER, NAVI_EXTERNAL_FRAGMENT_SHADER))
def test_phone_map_stream_does_not_apply_perspective_or_color_filters(shader):
  assert "insidePerspective" not in shader
  assert "perspectiveMapCoord" not in shader
  assert "strengthenRoute" not in shader
  assert "suppressTrafficColors" not in shader
  assert "routeOrange" not in shader


def test_rgba_map_stream_draws_original_texture_without_shader(monkeypatch):
  renderer = object.__new__(NaviMapTextureRenderer)
  cached = SimpleNamespace(mime="image/rgba", texture=object())
  source = rl.Rectangle(0, 0, 100, 100)
  dest = rl.Rectangle(10, 20, 200, 200)
  calls = []
  monkeypatch.setattr(rl, "begin_shader_mode", lambda value: calls.append(("begin", value)))
  monkeypatch.setattr(rl, "draw_texture_pro", lambda *args: calls.append(("draw", args)))
  monkeypatch.setattr(rl, "end_shader_mode", lambda: calls.append(("end",)))

  renderer._draw_cached(cached, source, dest)

  assert [call[0] for call in calls] == ["draw"]


def test_phone_map_crops_to_fill_panel_without_distorting_source(monkeypatch):
  renderer = object.__new__(NaviMapTextureRenderer)
  cached = SimpleNamespace(size=(1920, 1080))
  rect = rl.Rectangle(1360, 10, 790, 760)
  draws = []
  monkeypatch.setattr(rl, "draw_rectangle_rec", lambda *_: None)
  monkeypatch.setattr(renderer, "_draw_cached", lambda _, source, dest: draws.append((source, dest)))

  assert renderer._draw_texture(cached, rect)
  source, dest = draws[0]
  assert source.x == pytest.approx((1920 - source.width) / 2)
  assert source.y == 0
  assert source.width == pytest.approx(1080 * rect.width / rect.height)
  assert source.height == 1080
  assert dest.x == pytest.approx(rect.x)
  assert dest.y == pytest.approx(rect.y)
  assert dest.width == pytest.approx(rect.width)
  assert dest.height == pytest.approx(rect.height)
  assert source.width / source.height == pytest.approx(dest.width / dest.height)


def test_phone_map_tall_source_also_fills_panel(monkeypatch):
  renderer = object.__new__(NaviMapTextureRenderer)
  cached = SimpleNamespace(size=(1080, 1920))
  rect = rl.Rectangle(1360, 10, 790, 760)
  draws = []
  monkeypatch.setattr(rl, "draw_rectangle_rec", lambda *_: None)
  monkeypatch.setattr(renderer, "_draw_cached", lambda _, source, dest: draws.append((source, dest)))

  assert renderer._draw_texture(cached, rect)
  source, dest = draws[0]
  assert source.x == 0
  assert source.y == pytest.approx((1920 - source.height) / 2)
  assert source.width == 1080
  assert source.height == pytest.approx(1080 * rect.height / rect.width)
  assert (dest.x, dest.y, dest.width, dest.height) == (rect.x, rect.y, rect.width, rect.height)


def test_phone_map_reuses_unchanged_crop_geometry(monkeypatch):
  renderer = NaviMapTextureRenderer()
  cached = SimpleNamespace(size=(1920, 1080))
  rect = rl.Rectangle(1360, 10, 790, 760)
  sources = []
  monkeypatch.setattr(rl, "draw_rectangle_rec", lambda *_: None)
  monkeypatch.setattr(renderer, "_draw_cached", lambda _, source, _dest: sources.append(source))

  assert renderer._draw_texture(cached, rect)
  assert renderer._draw_texture(cached, rect)

  assert sources[0] is sources[1]


def test_local_map_reuses_perspective_strip_geometry():
  road_map = RoadMapTexture()
  panel = rl.Rectangle(1360, 10, 790, 760)

  first = road_map._perspective_strips(panel)
  second = road_map._perspective_strips(panel)
  resized = road_map._perspective_strips(rl.Rectangle(1360, 10, 780, 760))

  assert len(first) == 64
  assert first is second
  assert resized is not first


def test_local_route_projection_only_updates_with_navigation(monkeypatch):
  calls = []

  class FakeSubMaster:
    alive = {"carrotNavi": True}
    valid = {"carrotNavi": True}
    updated = {"carrotNavi": True}

    def __getitem__(self, _service):
      return object()

  expected = (rl.Vector2(1, 2), rl.Vector2(3, 4))
  view = object.__new__(CarrotNaviMapView)
  view._fallback_projected = None
  view._fallback_panel_key = None
  panel = rl.Rectangle(1360, 10, 790, 760)
  sm = FakeSubMaster()
  monkeypatch.setattr(
    "openpilot.selfdrive.ui.onroad.carrot_navi_map.map_state_from_carrot_navi",
    lambda *_: object(),
  )
  monkeypatch.setattr("openpilot.selfdrive.ui.onroad.carrot_navi_map.route_local_points", lambda _state: ())
  monkeypatch.setattr(
    "openpilot.selfdrive.ui.onroad.carrot_navi_map.project_route",
    lambda *_: calls.append(True) or expected,
  )

  assert view._fallback_route(sm, panel) is expected
  sm.updated["carrotNavi"] = False
  assert view._fallback_route(sm, panel) is expected

  assert len(calls) == 1


def test_onroad_map_source_filters_media_and_bounds_decoder_queue(monkeypatch):
  created = []

  class FakeSource:
    def __init__(self, **kwargs):
      created.append(kwargs)

  view = object.__new__(CarrotNaviMapView)
  view._phone_stream_enabled = False
  view._phone_source = None
  view._phone_map_active = False
  view._phone_map_updated_at = 0.0
  view._params = SimpleNamespace(put_nonblocking=lambda *_: None)
  monkeypatch.setattr("openpilot.selfdrive.ui.onroad.carrot_navi_map.create_phone_map_source", FakeSource)

  view._set_phone_stream_enabled(True)

  assert created == [{
    "media_keys": ONROAD_MAP_MEDIA_KEYS,
    "h264_queue_max": ONROAD_H264_QUEUE_MAX,
  }]


def test_phone_map_activity_param_is_only_written_on_transition():
  writes = []
  view = object.__new__(CarrotNaviMapView)
  view._phone_map_active = False
  view._params = SimpleNamespace(put_bool_nonblocking=lambda key, value: writes.append((key, value)))

  view._set_phone_map_active(True)
  view._set_phone_map_active(True)
  view._set_phone_map_active(False)

  assert writes == [
    ("CarrotNaviPhoneMapActive", True),
    ("CarrotNaviPhoneMapActive", False),
  ]


def test_map_resources_are_recreated_after_offroad_close(monkeypatch):
  sources, closed_sources, closed_renderers, bootstrap = [], [], [], []

  class Source:
    def __init__(self, **kwargs):
      sources.append(self)

    def close(self):
      closed_sources.append(self)

  class Renderer:
    def close(self):
      closed_renderers.append(self)

  monkeypatch.setattr("openpilot.selfdrive.ui.onroad.carrot_navi_map.create_phone_map_source", Source)
  monkeypatch.setattr("openpilot.selfdrive.ui.onroad.carrot_navi_map.NaviMapTextureRenderer", Renderer)
  view = object.__new__(CarrotNaviMapView)
  view._phone_stream_enabled = False
  view._phone_source = None
  view._phone_map_active = False
  view._phone_map_updated_at = 0.0
  view._phone_renderer = Renderer()
  view._road_map = SimpleNamespace(close=lambda: None)
  view._params = SimpleNamespace(put_nonblocking=lambda *args: bootstrap.append(args))

  view._set_phone_stream_enabled(True)
  first_source = view._phone_source
  view.close()
  assert view._phone_source is None
  assert closed_sources == [first_source]
  assert len(closed_renderers) == 1
  view._set_phone_stream_enabled(True)
  assert view._phone_source is sources[1]
  assert view._phone_source is not first_source
  assert len(bootstrap) == 2
  view.close()
  assert len(closed_sources) == len(closed_renderers) == 2


def test_phone_map_server_dependencies_are_loaded_only_on_enable():
  import subprocess
  import sys

  result = subprocess.run([sys.executable, '-c', '''
import sys
from openpilot.selfdrive.ui.onroad.carrot_navi_map import create_phone_map_source
assert "cluster_navi_source" not in sys.modules
class Socket:
  def close(self): pass
class Messaging:
  def sub_sock(self, *args, **kwargs): return Socket()
source = create_phone_map_source(messaging_module=Messaging())
assert "cluster_navi_source" in sys.modules
source.close()
'''], capture_output=True, text=True)
  assert result.returncode == 0, result.stderr


def test_local_map_buffer_is_lazy_reused_and_released(monkeypatch):
  import numpy as np
  from openpilot.selfdrive.ui.onroad.carrot_navi_map import MAP_COLOR_LUT, MAP_SIZE

  road = RoadMapTexture()
  assert road._rgba is None
  monkeypatch.setattr(rl, 'update_texture', lambda *_: None)
  monkeypatch.setattr(rl, 'unload_texture', lambda *_: None)
  road._texture = object()
  pixels = np.arange(MAP_SIZE ** 2, dtype=np.uint8)
  road._upload(pixels)
  first = road._rgba
  assert first.nbytes == 262144
  np.testing.assert_array_equal(first, MAP_COLOR_LUT[pixels])
  road._upload(pixels)
  assert road._rgba is first
  road.close()
  assert road._rgba is None
  road._texture = object()
  road._upload(pixels)
  assert road._rgba is not first
  np.testing.assert_array_equal(road._rgba, first)
