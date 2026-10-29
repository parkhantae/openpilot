"""Driver-authorized bounded SET pulses; no remembered-speed RES requests."""
import math


class PorterMainSet:
  def __init__(self, initial_main=False, allow_startup_gas=False):
    self.main = bool(initial_main)
    self.main_known = False
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
    self.retry_wait = 1.
    self.pending_release = False
    self.previous_gas = False
    self.gas_release_since = None
    self.main_since = None
    self.raw_previous_gas = False
    self.rearm_gas_since = None
    self.sent_key = None
    self.sample_seen = 0.
    self.preferred_delay = 0.
    self.retry_delay = 0.
    self.pulse_delay = 0.
    self.awaiting_stock = False
    self.slot_wait_since = None
    self.confirmed_slot = None
    self.allow_startup_gas = allow_startup_gas
    self.startup_released = False
    self.startup_gas_since = None
    self.startup_valid_since = None
    self.startup_grant = False
    self.startup_grant_since = None

  def update(self, now, key, *, main_pressed, manual_button, blocked, request, stock_enabled, configured, gas_pressed=False):
    # A one-update event, emitted only by actual stock-ON feedback. Other
    # button transmitters may adopt it without inferring success from TX.
    self.confirmed_slot = None
    fresh = key is not None and key != self.last_key
    if fresh:
      self.last_key = key
      self.sample_seen = now
    clock_ok = math.isfinite(now) and (self.last_time is None or 0 <= now - self.last_time <= .1 + 1e-9)
    self.last_time = now
    if not clock_ok:
      self.armed = False
    if not configured:
      self.armed = self.main = False
    tx_fresh = key is not None and key != self.sent_key

    def send(button):
      self.sent_key = key
      return button

    stock_rising = stock_enabled and not self.previous_stock
    self.previous_stock = stock_enabled
    if stock_rising:
      if (self.awaiting_stock and clock_ok and configured and now - self.started <= .5 and
          not manual_button and not main_pressed and not blocked and not gas_pressed):
        self.preferred_delay = self.pulse_delay
        self.confirmed_slot = self.pulse_delay
      self.awaiting_stock = False
      self.retry_delay = self.preferred_delay
    if manual_button or main_pressed or blocked or not configured or not clock_ok:
      self.awaiting_stock = False
      self.retry_delay = self.preferred_delay
    if configured and stock_rising and not main_pressed:
      # Stock engagement proves MAIN is on, but never restores revoked permission.
      self.main = True
      self.main_known = True
      if self.main_since is None:
        self.main_since = now
    if fresh:
      if main_pressed and not self.previous_main:
        self.main_known = True
        self.main = not self.main
        self.armed = self.main and configured
        self.main_since = now if self.armed else None
      self.previous_main = main_pressed
      if manual_button == 4:
        self.armed = False
    if blocked:
      self.armed = False
    startup_ready = (self.allow_startup_gas and configured and self.main and not self.main_known and clock_ok and
                     not blocked and not main_pressed and not manual_button and not stock_enabled)
    if not startup_ready:
      self.startup_released = self.startup_grant = False
      self.startup_gas_since = self.startup_valid_since = None
    else:
      if self.startup_valid_since is None:
        self.startup_valid_since = now
      if not gas_pressed:
        self.startup_released = True
      if gas_pressed and not self.raw_previous_gas and self.startup_released:
        self.startup_gas_since = now
      elif not gas_pressed and self.raw_previous_gas:
        if (self.startup_gas_since is not None and now - self.startup_gas_since >= .1 - 1e-9 and
            now - self.startup_valid_since >= .5 - 1e-9 and request):
          # A fresh driver pedal cycle grants one bounded trial, NOT knowledge
          # of OEM MAIN state. Only actual stock ON may synchronize that state.
          self.startup_grant = True
          self.startup_grant_since = now
          self.previous_gas = True
          self.main_since = self.startup_valid_since
        self.startup_gas_since = None
      if gas_pressed or not request:
        self.startup_grant = False
      if (self.startup_grant and not self.pressing and self.startup_grant_since is not None and
          now - self.startup_grant_since > .1 + 1e-9):
        self.startup_grant = False
    rearm_ready = (configured and self.main and self.main_known and clock_ok and not blocked and not main_pressed and
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
    eligible = (self.armed or self.startup_grant) and configured and clock_ok and not blocked and not main_pressed and not manual_button
    if eligible and not stock_enabled and self.previous_gas and not gas_pressed:
      self.gas_release_since = now
    self.previous_gas = gas_pressed if eligible and not stock_enabled else False
    if not eligible or stock_enabled or gas_pressed:
      self.gas_release_since = None
    elif not request and self.gas_release_since is not None and now - self.gas_release_since > .1 + 1e-9:
      # A brief lead/plan transition may straddle pedal release. Keep only a
      # 100ms observation window; never turn it into a delayed engagement queue.
      self.gas_release_since = None
    if not eligible or stock_enabled or not request or gas_pressed:
      self.slot_wait_since = None
      self.since = None
      if self.pressing:
        self.pending_release = True
        self.awaiting_stock = False
        self.startup_grant = False
      self.pressing = False
      if stock_enabled:
        self.attempts = 0
      if tx_fresh and self.pending_release and not main_pressed and not manual_button:
        self.pending_release = False
        return send(0)
      return None
    if self.pending_release:
      if tx_fresh:
        self.pending_release = False
        return send(0)
      return None
    if self.pressing:
      if now - self.started >= .12 - 1e-9 or self.frames >= 6:
        self.pressing = False
        self.startup_grant = False
        self.pending_release = True
        self.retry_delay = .01 - self.pulse_delay
        self.next_request = now + self.retry_wait
        if tx_fresh:
          self.pending_release = False
          return send(0)
      elif tx_fresh and now - self.sample_seen >= self.pulse_delay - 1e-9:
        self.frames += 1
        return send(2)
      return None
    if self.since is None:
      self.since = now
    # Gas release is the driver's immediate SET cue. Do not add a 100ms
    # confirmation dwell once all request/override guards are already valid.
    # Native MAIN settling, retry quiet periods and fresh-sample timing remain.
    release_ready = (self.gas_release_since is not None and self.main_since is not None and
                     now - self.main_since >= .5 - 1e-9)
    if now >= self.next_request and (release_ready or now - self.since >= .5 - 1e-9):
      delay = self.retry_delay
      if not tx_fresh or now - self.sample_seen < delay - 1e-9:
        self.slot_wait_since = now if self.slot_wait_since is None else self.slot_wait_since
        if tx_fresh and now - self.slot_wait_since >= .1 - 1e-9:
          delay = 0.
        else:
          return None
      self.slot_wait_since = None
      self.pulse_delay = delay
      self.awaiting_stock = True
      self.gas_release_since = None
      self.pressing = True
      self.started = now
      self.frames = 1
      self.attempts += 1
      self.retry_wait = 3. if self.attempts >= 3 else 1.
      if self.attempts >= 3:
        self.attempts = 0
      # Reserve the retry quiet period at the first SET, including attempts
      # interrupted by a new pedal/target change before normal pulse completion.
      self.next_request = now + self.retry_wait
      return send(2)
    return None
