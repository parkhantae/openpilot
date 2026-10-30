"""A short tap on the displayed gap; holds and drags never change it."""
from collections.abc import Callable


class GapTouch:
  MAX_DURATION = 0.5
  MAX_MOVEMENT = 35.0

  def __init__(self, on_tap: Callable[[], None]):
    self._on_tap = on_tap
    self._rects = ()
    self._enabled = False
    self._press = None
    self._was_awake = True

  def contains(self, pos) -> bool:
    return self._enabled and any(x <= pos.x < x + width and y <= pos.y < y + height
                                 for x, y, width, height in self._rects)

  def update(self, rects, events, *, enabled: bool, awake: bool = True) -> None:
    enabled = enabled and awake and self._was_awake
    self._was_awake = awake
    bounds = tuple((rect.x, rect.y, rect.width, rect.height) for rect in rects)
    if bounds != self._rects or not enabled:
      self._press = None
    self._rects, self._enabled = bounds, enabled
    if not enabled:
      return

    # Ignore a multi-finger gesture, including a primary release in the same batch.
    if any(event.slot != 0 and (event.left_pressed or event.left_down) for event in events):
      self._press = None
      return
    for event in events:
      if event.slot != 0:
        continue
      if event.left_pressed:
        self._press = (event.pos.x, event.pos.y, event.t) if self.contains(event.pos) else None
      elif self._press is not None:
        x, y, started = self._press
        moved = (event.pos.x - x) ** 2 + (event.pos.y - y) ** 2 > self.MAX_MOVEMENT ** 2
        valid = self.contains(event.pos) and not moved and 0 <= event.t - started <= self.MAX_DURATION
        if event.left_released:
          self._press = None
          if valid:
            self._on_tap()
        elif not valid:
          self._press = None
