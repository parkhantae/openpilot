from types import SimpleNamespace

import pytest
import pyray as rl

from openpilot.selfdrive.ui.onroad.carrot_navi_map import (
  CarrotNaviMapView,
  GeoPoint,
  SimpleMapState,
  carrot_navi_panel_rect,
  colorize_map,
  map_state_from_carrot_navi,
  project_map_point,
  project_route,
  route_local_points,
)
from openpilot.selfdrive.ui.onroad.carrot_navi_stream import NAVI_YUV_FRAGMENT_SHADER, map_frame_from_dashboard


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
  assert tuple(rgba[4:8]) == (64, 180, 255, 255)
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


def test_yuv_perspective_normalizes_decoder_stride_before_narrowing_map():
  assert "fragTexCoord.x / textureScaleX" in NAVI_YUV_FRAGMENT_SHADER
  assert "visibleMapCoord.x * textureScaleX" in NAVI_YUV_FRAGMENT_SHADER


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
