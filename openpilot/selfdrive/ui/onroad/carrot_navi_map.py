from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import sys
import time
from typing import Any

import numpy as np
import pyray as rl

from openpilot.selfdrive.carrot.carrot_navi_control import parse_carrot_navi_control
from openpilot.common.params import Params


CLUSTER_MODULE_DIR = str(Path(__file__).resolve().parents[2] / "carrot" / "cluster")
if CLUSTER_MODULE_DIR not in sys.path:
  sys.path.insert(0, CLUSTER_MODULE_DIR)
from cluster_navi_source import NaviIpcMediaSource  # noqa: E402
from openpilot.selfdrive.ui.onroad.carrot_navi_stream import NaviMapTextureRenderer, map_frame_from_dashboard  # noqa: E402


PANEL_WIDTH = 790.0
PANEL_RIGHT_MARGIN = 10.0
PANEL_TOP = 10.0
GUIDANCE_TOP_FROM_BOTTOM = 310.0
EARTH_RADIUS_M = 6_378_137.0
MAX_ROUTE_DISTANCE_M = 1_200.0

PANEL_COLOR = rl.Color(12, 18, 25, 70)
GRID_COLOR = rl.Color(70, 82, 94, 76)
ROUTE_BORDER_COLOR = rl.Color(8, 13, 18, 245)
ROUTE_COLOR = rl.Color(64, 180, 255, 255)
VEHICLE_COLOR = rl.Color(245, 249, 255, 255)
VEHICLE_BORDER_COLOR = rl.Color(40, 142, 255, 255)
MAP_SIZE = 256
MAP_EGO_Y = 192.0
MAP_METERS_PER_PIXEL = 800.0 / MAP_EGO_Y
PERSPECTIVE_NEAR_Y = 0.82
PERSPECTIVE_HORIZON_Y = 0.0
PERSPECTIVE_DEPTH_M = 120.0
PERSPECTIVE_FAR_START = 0.40
PERSPECTIVE_FAR_STRENGTH = 1.8
PERSPECTIVE_TOP_WIDTH = 0.80
VALID_MAP_HOLD_S = 5.0


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
      max(1.0, rect.height - GUIDANCE_TOP_FROM_BOTTOM - PANEL_TOP),
    )

  margin = 12.0
  width = max(1.0, rect.width - 2.0 * margin)
  height = max(1.0, rect.height * 0.28)
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


def project_map_point(source_x: float, source_y: float, rect: rl.Rectangle) -> rl.Vector2:
  """Project the one-meter map raster into a heading-up 3D road plane."""
  forward_m = MAP_EGO_Y - source_y
  if forward_m >= 0.0:
    raw_depth = forward_m / (forward_m + PERSPECTIVE_DEPTH_M)
    raster_depth = MAP_EGO_Y / (MAP_EGO_Y + PERSPECTIVE_DEPTH_M)
    depth = min(1.0, raw_depth / raster_depth)
    if depth > PERSPECTIVE_FAR_START:
      far = (depth - PERSPECTIVE_FAR_START) / (1.0 - PERSPECTIVE_FAR_START)
      depth += PERSPECTIVE_FAR_STRENGTH * far * far * (1.0 - depth)
    screen_y = rect.y + rect.height * (PERSPECTIVE_NEAR_Y - (PERSPECTIVE_NEAR_Y - PERSPECTIVE_HORIZON_Y) * depth)
    # Fit every source row inside a mild trapezoid. The far edge narrows to
    # 80%, but no map content is cropped because the complete row is scaled.
    width_factor = 1.0 - (1.0 - PERSPECTIVE_TOP_WIDTH) * depth
  else:
    screen_y = rect.y + rect.height * (PERSPECTIVE_NEAR_Y + 0.18 * min(1.0, -forward_m / 64.0))
    width_factor = 1.0
  scale = rect.width / MAP_SIZE * width_factor
  return rl.Vector2(rect.x + rect.width * 0.5 + (source_x - MAP_SIZE * 0.5) * scale, screen_y)


def project_route(points: tuple[LocalPoint, ...], rect: rl.Rectangle) -> tuple[rl.Vector2, ...]:
  if len(points) < 2:
    return ()

  return tuple(project_map_point(
    MAP_SIZE * 0.5 + point.right_m / MAP_METERS_PER_PIXEL,
    MAP_EGO_Y - point.forward_m / MAP_METERS_PER_PIXEL,
    rect,
  ) for point in points)


def _draw_grid(rect: rl.Rectangle) -> None:
  for source_x in (32.0, 80.0, 128.0, 176.0, 224.0):
    rl.draw_line_v(project_map_point(source_x, 0.0, rect), project_map_point(source_x, 256.0, rect), GRID_COLOR)
  for source_y in (0.0, 48.0, 96.0, 144.0, 192.0, 224.0):
    rl.draw_line_v(project_map_point(0.0, source_y, rect), project_map_point(256.0, source_y, rect), GRID_COLOR)


class RoadMapTexture:
  """Nonblocking reader for mapsd's lightweight local road raster."""
  def __init__(self) -> None:
    self._client = None
    self._texture = None
    self._retry_at = 0.0
    self._updated_at = 0.0
    self._has_roads = False

  def draw(self, rect: rl.Rectangle) -> bool:
    now = time.monotonic()
    if self._client is None:
      from msgq.visionipc import VisionIpcClient, VisionStreamType
      self._client = VisionIpcClient("mapsd_ui", VisionStreamType.VISION_STREAM_MAP, True)
    if not self._client.is_connected() and now >= self._retry_at:
      self._client.connect(False)
      self._retry_at = now + 1.0
    if self._client.is_connected():
      buffer = self._client.recv(0)
      if buffer is not None and (buffer.width, buffer.height) == (MAP_SIZE, MAP_SIZE) and len(buffer.data) >= MAP_SIZE ** 2:
        pixels = bytes(buffer.data[:MAP_SIZE ** 2])
        # mapsd deliberately sends black while a tile/instruction update is in
        # flight. Retain the last valid frame instead of flashing to fallback.
        if any(pixels):
          self._has_roads = True
          self._updated_at = int(self._client.timestamp_eof) * 1e-9
          self._upload(pixels)

    if self._texture is None or not self._has_roads or not 0.0 <= now - self._updated_at < VALID_MAP_HOLD_S:
      return False

    # Four-pixel strips approximate vertical road-plane perspective without
    # adding a shader or GPU render target.
    for source_y in range(0, MAP_SIZE, 4):
      next_y = min(MAP_SIZE, source_y + 4)
      middle_y = (source_y + next_y) * 0.5
      left = project_map_point(0.0, middle_y, rect)
      right = project_map_point(float(MAP_SIZE), middle_y, rect)
      top = project_map_point(MAP_SIZE * 0.5, float(source_y), rect).y
      bottom = project_map_point(MAP_SIZE * 0.5, float(next_y), rect).y
      source = rl.Rectangle(0.0, float(source_y), float(MAP_SIZE), float(next_y - source_y))
      destination = rl.Rectangle(left.x, top, right.x - left.x, max(1.0, bottom - top + 0.75))
      rl.draw_texture_pro(
        self._texture, source, destination, rl.Vector2(0.0, 0.0), 0.0, rl.WHITE,
      )
    return True

  def _upload(self, pixels: bytes) -> None:
    payload = colorize_map(pixels)
    if self._texture is None:
      image = rl.Image(None, MAP_SIZE, MAP_SIZE, 1, rl.PixelFormat.PIXELFORMAT_UNCOMPRESSED_R8G8B8A8)
      self._texture = rl.load_texture_from_image(image)
      rl.set_texture_filter(self._texture, rl.TextureFilter.TEXTURE_FILTER_BILINEAR)
    data = rl.ffi.cast("void *", rl.ffi.from_buffer("const unsigned char[]", payload))
    rl.update_texture(self._texture, data)

  def close(self) -> None:
    if self._texture is not None:
      rl.unload_texture(self._texture)
      self._texture = None
    self._client = None


def colorize_map(pixels: bytes) -> bytes:
  gray = np.frombuffer(pixels, dtype=np.uint8)
  rgba = np.empty((MAP_SIZE * MAP_SIZE, 4), dtype=np.uint8)
  rgba[:, :3] = (180, 194, 208)
  rgba[:, 3] = np.clip(45 + gray.astype(np.uint16) * 3 // 5, 45, 195).astype(np.uint8)
  background = gray == 0
  rgba[background] = (8, 14, 22, 45)
  # mapsd draws the active route at intensity 128. Color that already-aligned
  # route instead of reprojecting phone coordinates against a snapped map pose.
  route = (gray >= 105) & (gray <= 175)
  rgba[route] = (64, 180, 255, 255)
  return rgba.tobytes()


def _draw_route(points: tuple[rl.Vector2, ...], rect: rl.Rectangle) -> None:
  for start, end in zip(points, points[1:], strict=False):
    depth = min(1.0, max(0.0, ((start.y + end.y) * 0.5 - rect.y) / rect.height))
    rl.draw_line_ex(start, end, 10.0 + 18.0 * depth, ROUTE_BORDER_COLOR)
    rl.draw_line_ex(start, end, 5.0 + 13.0 * depth, ROUTE_COLOR)


def _draw_vehicle(rect: rl.Rectangle) -> None:
  vehicle = project_map_point(MAP_SIZE * 0.5, MAP_EGO_Y, rect)
  x, y = vehicle.x, vehicle.y
  outer = (rl.Vector2(x, y - 30), rl.Vector2(x - 23, y + 27), rl.Vector2(x + 23, y + 27))
  inner = (rl.Vector2(x, y - 22), rl.Vector2(x - 16, y + 19), rl.Vector2(x + 16, y + 19))
  rl.draw_triangle(*outer, VEHICLE_BORDER_COLOR)
  rl.draw_triangle(*inner, VEHICLE_COLOR)


class CarrotNaviMapView:
  def __init__(self) -> None:
    self._road_map = RoadMapTexture()
    self._params = Params()
    self._phone_source: NaviIpcMediaSource | None = None
    self._phone_renderer = NaviMapTextureRenderer()
    self._phone_stream_enabled = False
    self._phone_map_active = False

  def _set_phone_map_active(self, active: bool) -> None:
    active = bool(active)
    if active == self._phone_map_active:
      return
    self._phone_map_active = active
    try:
      self._params.put_bool_nonblocking("CarrotNaviPhoneMapActive", active)
    except Exception:
      pass

  def _set_phone_stream_enabled(self, enabled: bool) -> None:
    enabled = bool(enabled)
    if enabled == self._phone_stream_enabled:
      return
    self._phone_stream_enabled = enabled
    if enabled:
      self._phone_source = NaviIpcMediaSource()
      try:
        self._params.put_nonblocking("CarrotNaviWebBootstrapRequest", f"ui-{time.time_ns():x}")
      except Exception:
        pass
    else:
      self._set_phone_map_active(False)
      if self._phone_source is not None:
        self._phone_source.close()
        self._phone_source = None
      self._phone_renderer.close()
      self._phone_renderer = NaviMapTextureRenderer()

  def render(self, content_rect: rl.Rectangle, enabled: bool, sm: Any) -> bool:
    self._set_phone_stream_enabled(enabled)
    if not enabled:
      return False

    # Prefer the decoded phone map before parsing/projecting the local route.
    # This keeps the common CarrotNM path to one decoder update and one draw.
    panel = carrot_navi_panel_rect(content_rect)
    if self._phone_source is not None:
      dashboard = self._phone_source.update(None)
      phone_frame = map_frame_from_dashboard(dashboard)
      if phone_frame is not None:
        rl.begin_scissor_mode(int(panel.x), int(panel.y), int(panel.width), int(panel.height))
        rendered = self._phone_renderer.draw(phone_frame, panel)
        rl.end_scissor_mode()
        rl.begin_scissor_mode(
          int(content_rect.x), int(content_rect.y), int(content_rect.width), int(content_rect.height),
        )
        if rendered:
          self._set_phone_map_active(True)
          rl.draw_rectangle_rounded_lines_ex(panel, 0.08, 8, 2.0, rl.Color(92, 112, 132, 180))
          return True

    self._set_phone_map_active(False)
    try:
      state = map_state_from_carrot_navi(
        sm["carrotNavi"], bool(sm.alive["carrotNavi"]), bool(sm.valid["carrotNavi"]),
      )
    except Exception:
      state = None
    if state is None:
      return False

    projected = project_route(route_local_points(state), panel)
    if len(projected) < 2:
      return False
    rl.begin_scissor_mode(int(panel.x), int(panel.y), int(panel.width), int(panel.height))
    rl.draw_rectangle_rounded(panel, 0.08, 8, PANEL_COLOR)
    has_aligned_map = self._road_map.draw(panel)
    if not has_aligned_map:
      _draw_grid(panel)
    # Restore a translucent navy cast over the raster so the roads stay readable
    # without competing with the blue active route and the driving HUD.
    rl.draw_rectangle_rec(panel, rl.Color(8, 14, 22, 10))
    if not has_aligned_map:
      _draw_route(projected, panel)
    _draw_vehicle(panel)
    rl.draw_rectangle_rounded_lines_ex(panel, 0.08, 8, 2.0, rl.Color(92, 112, 132, 150))
    rl.end_scissor_mode()
    # The road view owns a content scissor around us; restore it after using the
    # tighter map clip because raylib's scissor state is not a stack.
    rl.begin_scissor_mode(
      int(content_rect.x), int(content_rect.y), int(content_rect.width), int(content_rect.height),
    )
    return True

  def close(self) -> None:
    self._set_phone_stream_enabled(False)
    self._road_map.close()
