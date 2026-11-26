"""Web background work must not invalidate a native staged update or reboot it."""
import asyncio
from contextlib import nullcontext
import sys
from types import ModuleType, SimpleNamespace as NS

import pytest

from openpilot.selfdrive.carrot.server.services import auto_update, git_status


def test_native_update_blocks_background_ref_refresh_without_touching_git(monkeypatch):
  monkeypatch.setattr(git_status, '_cache', None)
  monkeypatch.setattr(git_status, '_lock', None)
  monkeypatch.setattr(git_status, 'repo_lock', nullcontext)
  monkeypatch.setattr(git_status, 'native_update_active', lambda: True)

  async def forbidden():
    pytest.fail('background fetch would change .git after .overlay_init')

  monkeypatch.setattr(git_status, '_read_status', forbidden)
  result = asyncio.run(git_status.get_git_status(force=True))
  assert result['state'] == 'native_update'
  assert not result['available']


def test_cached_behind_result_cannot_start_a_web_pull_during_native_install(monkeypatch):
  async def status():
    return {'available': True, 'state': 'ok', 'behind': 1, 'target_head': 'new', 'head': 'old', 'branch': 'c3-pht-porter'}

  async def forbidden(*args):
    pytest.fail('web update must not prepare or pull during native update')

  monkeypatch.setattr(auto_update, 'get_git_status', status)
  monkeypatch.setattr(auto_update, '_last_pull_at', float('-inf'))
  monkeypatch.setattr(auto_update, 'repo_lock', nullcontext)
  monkeypatch.setattr(auto_update, 'native_update_active', lambda: True)
  monkeypatch.setattr(auto_update, 'prepare_repo', forbidden)
  result = asyncio.run(auto_update._attempt_update(NS(ready=lambda: True)))
  assert result == (False, False, '')


def test_an_already_armed_web_reboot_waits_for_explicit_native_install(monkeypatch):
  cereal = ModuleType('openpilot.cereal')
  cereal.messaging = NS(SubMaster=lambda services: NS(update=lambda *args: pytest.fail('native staging must defer the reboot monitor')))
  monkeypatch.setitem(sys.modules, 'openpilot.cereal', cereal)
  monkeypatch.setattr(auto_update, 'native_update_active', lambda: True)
  monkeypatch.setattr(auto_update, '_auto_reboot_mode', lambda: auto_update.AUTO_REBOOT_PARK)
  monkeypatch.setattr(auto_update, 'write_auto_update_event', lambda *args, **kw: {'ok': True})
  monkeypatch.setattr(auto_update, '_request_reboot', lambda: pytest.fail('unexpected automatic reboot'))

  async def stop_after_observing_deferral(delay):
    raise asyncio.CancelledError

  monkeypatch.setattr(auto_update.asyncio, 'sleep', stop_after_observing_deferral)
  with pytest.raises(asyncio.CancelledError):
    asyncio.run(auto_update._wait_for_auto_reboot(auto_update.AUTO_REBOOT_PARK, 'new'))
