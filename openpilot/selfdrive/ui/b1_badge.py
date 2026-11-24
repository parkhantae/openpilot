"""Persistent B1 link indicator on the C3 and C4 home and driving screens."""
import json
from pathlib import Path
import time

ENROLLED = Path('/data/carrot/b1-monitor.json')
STATUS = Path('/dev/shm/carrot-b1-link.json')
FOOTER_FONT_SIZE = 28
CONNECTED_STATES = frozenset(('ready', 'waiting', 'sending', 'driver_override', 'error',
                              'relay_ready', 'relay_waiting', 'relay_on', 'relay_error'))
LABELS = {
  'relay_ready': ('S3 · 접점 준비', (96, 232, 162)),
  'relay_waiting': ('S3 · 접점 대기', (96, 218, 243)),
  'relay_on': ('S3 · 접점 출력', (96, 218, 243)),
  'relay_error': ('S3 · 접점 차단', (252, 128, 110)),
  'updating': ('S3 · 업데이트', (96, 218, 243)),
  'offline': ('S3 · 연결 대기', (170, 178, 188)),
  'auth': ('S3 · 인증 중', (255, 197, 89)),
  'missing': ('S3 · CAN 대기', (202, 147, 255)),
  'ready': ('S3 · CAN 연결', (96, 232, 162)),
  'waiting': ('S3 · CAN 연결', (96, 232, 162)),
  'sending': ('S3 · 송신', (96, 218, 243)),
  'driver_override': ('S3 · 레버 우선', (255, 197, 89)),
  'error': ('S3 · CAN 오류', (252, 128, 110)),
}


def status(now, enrolled=ENROLLED, path=STATUS):
  if not enrolled.is_file():
    return None
  try:
    with path.open('rb') as stream:
      record = json.loads(stream.read(4096))
    if 0 <= now-record['time'] < 2 and record['state'] in LABELS:
      if record.get('mode') == 'relay' and record['state'] == 'waiting' and record.get('outputs') in (1, 2):
        return 'relay_on'
      if record.get('mode') == 'relay' and 'relay_' + record['state'] in LABELS:
        return 'relay_' + record['state']
      return record['state']
  except (OSError, KeyError, ValueError, TypeError):
    pass
  return 'offline'


_next = 0.
_state = None


def presentation():
  global _next, _state
  now = time.monotonic()
  if now >= _next or now < _next - .35:
    _state = status(now)
    _next = now + .35
  if _state in CONNECTED_STATES:
    return 'S3 연결됨', (255, 255, 255)
  return None


def draw_footer(rect, label, *, left=None, right=None):
  """Use the same plain white text and baseline as the footer IP address."""
  import pyray as rl
  from openpilot.selfdrive.ui import UI_BORDER_SIZE
  from openpilot.system.ui.lib.application import FontWeight, gui_app
  from openpilot.system.ui.lib.text_draw import draw_text_ui_style
  font = gui_app.font(FontWeight.DISPLAY)
  x = left if left is not None else right
  draw_text_ui_style(label, x, rect.y + rect.height - UI_BORDER_SIZE - 2, FOOTER_FONT_SIZE, rl.WHITE,
                     font=font, align="left_top" if left is not None else "right_top", y_offset=0.0)


def draw(rect, *, footer_right=None):
  current = presentation()
  if current is None:
    return
  label, rgb = current
  if footer_right is not None:
    return draw_footer(rect, label, right=footer_right)
  import pyray as rl
  from openpilot.system.ui.lib.application import FontWeight, gui_app
  font = gui_app.font(FontWeight.DISPLAY)
  size = 24 if rect.width >= 1200 else 16
  width = size*8
  height = size*1.55
  x, y = rect.x + rect.width*.72 - width/2, rect.y + size*.55
  rl.draw_rectangle_rounded(rl.Rectangle(x, y, width, height), .7, 8, rl.Color(10, 18, 25, 220))
  rl.draw_circle(int(x+size*.62), int(y+size*.77), size*.19, rl.Color(*rgb, 255))
  rl.draw_text_ex(font, label, rl.Vector2(x+size*1.05, y+size*.24), size, 0, rl.WHITE)
  return x
