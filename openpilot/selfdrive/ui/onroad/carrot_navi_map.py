from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

import pyray as rl

from openpilot.selfdrive.carrot.carrot_navi_control import parse_carrot_navi_control


PANEL_WIDTH = 790.0
PANEL_HEIGHT = 360.0
PANEL_RIGHT_MARGIN = 10.0
PANEL_TOP = 170.0
EARTH_RADIUS_M = 6_378_137.0
MAX_ROUTE_DISTANCE_M = 1_200.0

PANEL_COLOR = rl.Color(12, 18, 25, 224)
GRID_COLOR = rl.Color(70, 82, 94, 76)
ROUTE_BORDER_COLOR = rl.Color(8, 13, 18, 245)
ROUTE_COLOR = rl.Color(40, 142, 255, 255)
VEHICLE_COLOR = rl.Color(245, 249, 255, 255)
VEHICLE_BORDER_COLOR = rl.Color(40, 142, 255, 255)


@dataclass(frozen=True)
class GeoPoint:
  latitude: float
  longitude: float


@dataclass(frozen=True)
class SimpleMapState:
  vehicle: GeoPoint
  heading_deg: float
  route: tuple[GeoPoint, ...]


@dataclass(frozen=True)
class LocalPoint:
  right_m: float
  forward_m: float


def carrot_navi_panel_rect(rect: rl.Rectangle) -> rl.Rectangle:
  """Match the 790 px lower-right turn panel and place the map above it."""
  if rect.width >= 1200.0:
    return rl.Rectangle(
      rect.x + rect.width - PANEL_WIDTH - PANEL_RIGHT_MARGIN,
      rect.y + PANEL_TOP,
      PANEL_WIDTH,
      PANEL_HEIGHT,
    )

  margin = 12.0
  width = max(1.0, rect.width - 2.0 * margin)
  height = min(PANEL_HEIGHT, max(1.0, rect.height * 0.28))
  return rl.Rectangle(rect.x + margin, rect.y + margin, width, height)


def map_state_from_carrot_navi(message: Any, alive: bool, valid: bool) -> SimpleMapState | None:
  if not alive or not valid:
    return None
  control = parse_carrot_navi_control(message)
  if control is None or not control.vehicle.present or not control.route.present or len(control.route.polyline) < 2:
    return None

  vehicle = GeoPoint(control.vehicle.latitude, control.vehicle.longitude)
  route = tuple(GeoPoint(latitude, longitude) for latitude, longitude in control.route.polyline)
  return SimpleMapState(vehicle, control.vehicle.heading_deg, route)


def _offset_m(origin: GeoPoint, point: GeoPoint) -> tuple[float, float]:
  lat0 = math.radians(origin.latitude)
  east = math.radians(point.longitude - origin.longitude) * EARTH_RADIUS_M * math.cos(lat0)
  north = math.radians(point.latitude - origin.latitude) * EARTH_RADIUS_M
  return east, north


def _heading_up(origin: GeoPoint, point: GeoPoint, heading_deg: float) -> LocalPoint:
  east, north = _offset_m(origin, point)
  heading = math.radians(heading_deg)
  return LocalPoint(
    right_m=east * math.cos(heading) - north * math.sin(heading),
    forward_m=east * math.sin(heading) + north * math.cos(heading),
  )


def route_local_points(state: SimpleMapState) -> tuple[LocalPoint, ...]:
  offsets = [_offset_m(state.vehicle, point) for point in state.route]
  nearest = min(range(len(offsets)), key=lambda index: offsets[index][0] ** 2 + offsets[index][1] ** 2)
  start = max(0, nearest - 2)

  result: list[LocalPoint] = []
  travelled = 0.0
  previous: GeoPoint | None = None
  for point in state.route[start:]:
    if previous is not None:
      dx, dy = _offset_m(previous, point)
      travelled += math.hypot(dx, dy)
    if travelled > MAX_ROUTE_DISTANCE_M:
      break
    result.append(_heading_up(state.vehicle, point, state.heading_deg))
    previous = point
  return tuple(result)


def project_route(points: tuple[LocalPoint, ...], rect: rl.Rectangle) -> tuple[rl.Vector2, ...]:
  if len(points) < 2:
    return ()

  pad_x = 54.0
  pad_top = 38.0
  vehicle_y = rect.y + rect.height * 0.78
  usable_width = max(1.0, rect.width - 2.0 * pad_x)
  usable_forward = max(1.0, vehicle_y - (rect.y + pad_top))
  max_forward = max(80.0, max(point.forward_m for point in points))
  max_side = max(30.0, max(abs(point.right_m) for point in points))
  scale = min(usable_forward / max_forward, usable_width / (2.0 * max_side))
  center_x = rect.x + rect.width * 0.5
  return tuple(rl.Vector2(center_x + point.right_m * scale, vehicle_y - point.forward_m * scale) for point in points)


def _draw_grid(rect: rl.Rectangle) -> None:
  for fraction in (0.25, 0.5, 0.75):
    x = int(rect.x + rect.width * fraction)
    y = int(rect.y + rect.height * fraction)
    rl.draw_line(x, int(rect.y + 18), x, int(rect.y + rect.height - 18), GRID_COLOR)
    rl.draw_line(int(rect.x + 18), y, int(rect.x + rect.width - 18), y, GRID_COLOR)


def _draw_route(points: tuple[rl.Vector2, ...]) -> None:
  for start, end in zip(points, points[1:], strict=False):
    rl.draw_line_ex(start, end, 18.0, ROUTE_BORDER_COLOR)
    rl.draw_line_ex(start, end, 10.0, ROUTE_COLOR)


def _draw_vehicle(rect: rl.Rectangle) -> None:
  x = rect.x + rect.width * 0.5
  y = rect.y + rect.height * 0.78
  outer = (rl.Vector2(x, y - 22), rl.Vector2(x - 17, y + 20), rl.Vector2(x + 17, y + 20))
  inner = (rl.Vector2(x, y - 15), rl.Vector2(x - 11, y + 14), rl.Vector2(x + 11, y + 14))
  rl.draw_triangle(*outer, VEHICLE_BORDER_COLOR)
  rl.draw_triangle(*inner, VEHICLE_COLOR)


class CarrotNaviMapView:
  def render(self, content_rect: rl.Rectangle, enabled: bool, sm: Any) -> bool:
    if not enabled:
      return False
    try:
      state = map_state_from_carrot_navi(
        sm["carrotNavi"], bool(sm.alive["carrotNavi"]), bool(sm.valid["carrotNavi"]),
      )
    except Exception:
      state = None
    if state is None:
      return False

    panel = carrot_navi_panel_rect(content_rect)
    projected = project_route(route_local_points(state), panel)
    if len(projected) < 2:
      return False
    rl.draw_rectangle_rounded(panel, 0.08, 8, PANEL_COLOR)
    _draw_grid(panel)
    _draw_route(projected)
    _draw_vehicle(panel)
    rl.draw_rectangle_rounded_lines_ex(panel, 0.08, 8, 2.0, rl.Color(92, 112, 132, 150))
    return True

  def close(self) -> None:
    pass
