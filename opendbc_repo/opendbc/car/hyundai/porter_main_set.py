"""Physical-MAIN-only, bounded SET pulses; no remembered-speed RES requests."""
import math


class PorterMainSet:
  def __init__(self):
    self.main = False
    self.previous_main = False
    self.previous_stock = False
    self.armed = False
    self.last_time = None
    self.last_key = None
    self.since = None
    self.pressing = False
    self.started = 0.
    self.frames = 0
    self.next_request = 0.
    self.attempts = 0
    self.pending_release = False

  def update(self, now, key, *, main_pressed, manual_button, blocked, request, stock_enabled, configured):
    fresh = key is not None and key != self.last_key
    if fresh:
      self.last_key = key
    clock_ok = math.isfinite(now) and (self.last_time is None or 0 <= now - self.last_time <= .1 + 1e-9)
    self.last_time = now
    if not clock_ok:
      self.armed = False
    if not configured:
      self.armed = self.main = False
    stock_rising = stock_enabled and not self.previous_stock
    self.previous_stock = stock_enabled
    if configured and stock_rising and not main_pressed:
      # Stock engagement proves MAIN is on, but never restores revoked permission.
      self.main = True
    if fresh:
      if main_pressed and not self.previous_main:
        self.main = not self.main
        self.armed = self.main and configured
      self.previous_main = main_pressed
      if manual_button == 4:
        self.armed = False
    if blocked:
      self.armed = False
    eligible = self.armed and configured and clock_ok and not blocked and not main_pressed and not manual_button
    if not eligible or stock_enabled or not request:
      self.since = None
      if self.pressing:
        self.pending_release = True
      self.pressing = False
      if stock_enabled:
        self.attempts = 0
      if fresh and self.pending_release and not main_pressed and not manual_button:
        self.pending_release = False
        return 0
      return None
    if self.pending_release:
      if fresh:
        self.pending_release = False
        return 0
      return None
    if self.pressing:
      if now - self.started >= .06 - 1e-9 or self.frames >= 3:
        self.pressing = False
        self.pending_release = True
        self.next_request = now + (3. if self.attempts >= 3 else 1.)
        if self.attempts >= 3:
          self.attempts = 0
        if fresh:
          self.pending_release = False
          return 0
      elif fresh:
        self.frames += 1
        return 2
      return None
    if self.since is None:
      self.since = now
    if fresh and now >= self.next_request and now - self.since >= .5 - 1e-9:
      self.pressing = True
      self.started = now
      self.frames = 1
      self.attempts += 1
      return 2
    return None
