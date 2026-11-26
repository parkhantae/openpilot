"""One explicit offroad update, independent of the background-update setting."""
from contextlib import contextmanager, ExitStack
import time

REQUEST_KEY = "UpdaterManualRequest"


class UserRequest:
  NONE = 0
  CHECK = 1
  FETCH = 2


def pending_request(params) -> int:
  value = params.get_int(REQUEST_KEY)
  return value if value in (UserRequest.CHECK, UserRequest.FETCH) else UserRequest.NONE


def updater_enabled(started: bool, params) -> bool:
  return not started and not params.get_bool("DisableUpdates") and (
    params.get_bool("SoftwareMenu") or pending_request(params) != UserRequest.NONE
  )


def finish_request(params, request: int) -> None:
  if request != UserRequest.NONE and pending_request(params) == request:
    params.remove(REQUEST_KEY)


def native_update_active(params=None) -> bool:
  if params is None:
    # Web starts before the native Params extension is built. Keep that import
    # lazy, and tolerate a previous registry during the startup rebuild.
    try:
      from openpilot.common.params import Params
    except ImportError:
      return False
    params = Params()
    if REQUEST_KEY.encode() not in params.all_keys():
      return params.get_bool("UpdateAvailable")
  return pending_request(params) != UserRequest.NONE or params.get_bool("UpdateAvailable") or (
    params.get("UpdaterState") in ("checking...", "downloading...", "finalizing update...")
  )


@contextmanager
def update_lock(timeout: float = 60.0):
  from openpilot.common.repo_update import RepoBusyError, repo_lock

  deadline = time.monotonic() + timeout
  with ExitStack() as stack:
    while True:
      try:
        stack.enter_context(repo_lock())
        break
      except RepoBusyError:
        if time.monotonic() >= deadline:
          raise
        time.sleep(0.2)
    yield
