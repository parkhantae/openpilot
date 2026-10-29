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
    self.previous_gas = False
    self.gas_release_since = None
    self.main_since = None
    self.raw_previous_gas = False
    self.rearm_gas_since = None

  def update(self, now, key, *, main_pressed, manual_button, blocked, request, stock_enabled, configured, gas_pressed=False):
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
      if self.main_since is None:
        self.main_since = now
    if fresh:
      if main_pressed and not self.previous_main:
        self.main = not self.main
        self.armed = self.main and configured
        self.main_since = now if self.armed else None
      self.previous_main = main_pressed
      if manual_button == 4:
        self.armed = False
    if blocked:
      self.armed = False
    rearm_ready = (configured and self.main and clock_ok and not blocked and not main_pressed and
                   not manual_button and not stock_enabled)
    if not rearm_ready:
      self.rearm_gas_since = None
    elif not self.armed:
      if gas_pressed and not self.raw_previous_gas:
        self.rearm_gas_since = now
      elif not gas_pressed and self.raw_previous_gas:
        if self.rearm_gas_since is not None and now - self.rearm_gas_since >= .1 - 1e-9 and request:
          self.armed = True
          self.previous_gas = True
        self.rearm_gas_since = None
    self.raw_previous_gas = gas_pressed
    eligible = self.armed and configured and clock_ok and not blocked and not main_pressed and not manual_button
    if eligible and not stock_enabled and self.previous_gas and not gas_pressed:
      self.gas_release_since = now
    self.previous_gas = gas_pressed if eligible and not stock_enabled else False
    if not eligible or stock_enabled or gas_pressed:
      self.gas_release_since = None
    elif not request:
      self.gas_release_since = None
    if not eligible or stock_enabled or not request or gas_pressed:
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
      if now - self.started >= .12 - 1e-9 or self.frames >= 6:
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
    release_confirmed = (self.gas_release_since is not None and now - self.gas_release_since >= .1 - 1e-9 and
                         self.main_since is not None and now - self.main_since >= .5 - 1e-9)
    if fresh and now >= self.next_request and (release_confirmed or now - self.since >= .5 - 1e-9):
      self.gas_release_since = None
      self.pressing = True
      self.started = now
      self.frames = 1
      self.attempts += 1
      return 2
    return None
