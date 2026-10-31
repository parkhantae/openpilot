from types import SimpleNamespace

import pytest
import pyray as rl

from openpilot.selfdrive.ui.onroad.carrot_navi_map import (
  GeoPoint,
  SimpleMapState,
  carrot_navi_panel_rect,
  map_state_from_carrot_navi,
  project_route,
  route_local_points,
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


def test_panel_matches_lower_right_guidance_width_and_x():
  panel = carrot_navi_panel_rect(rl.Rectangle(0, 0, 2160, 1080))

  assert panel.x == 1360
  assert panel.y == 10
  assert panel.width == 790
  assert panel.height == 790


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


def test_projected_route_uses_same_one_meter_scale_as_road_raster():
  state = map_state_from_carrot_navi(carrot_navi_message(), True, True)
  assert state is not None
  panel = rl.Rectangle(1360, 10, 790, 790)
  projected = project_route(route_local_points(state), panel)

  assert len(projected) == 3
  scale = panel.width / 256
  assert projected[0].x == pytest.approx(panel.x + panel.width / 2)
  assert projected[0].y == pytest.approx(panel.y + 192 * scale)
  assert projected[1].y == pytest.approx(projected[0].y - 55.66 * scale, abs=1.0)
