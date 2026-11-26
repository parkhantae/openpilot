"""Drive real UI callbacks and updater transactions; replace only display/OS mounting."""

import ast
from collections import defaultdict
from contextlib import nullcontext
import datetime
import importlib.util
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[4]
SOURCE = Path(os.environ.get('PHT_UPDATER_SOURCE_ROOT', ROOT))


def load(name, path):
  spec = importlib.util.spec_from_file_location(name, path)
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


manual = load('manual_request_test', ROOT / 'openpilot/system/updated/manual_request.py')
process = load('update_process_test', ROOT / 'openpilot/system/updated/process.py')


class Params(dict):
  def get(self, key, default=None, *, return_default=False):
    return super().get(key, 0 if return_default else default)

  def get_bool(self, key):
    return bool(self.get(key, False))

  def get_int(self, key):
    return int(self.get(key, 0))

  def put(self, key, value):
    self[key] = value

  put_bool = put_int = put

  def remove(self, key):
    self.pop(key, None)


class Item:
  def __init__(self, text='', value='', **kwargs):
    self.action_item = self
    self.text, self.value = text, value
    self.enabled, self.visible, self.description = True, True, ''

  def set_value(self, value):
    self.value = value

  def set_text(self, value):
    self.text = value

  def set_enabled(self, value):
    self.enabled = value

  def set_visible(self, value):
    self.visible = value

  def set_description(self, value):
    self.description = value


@pytest.fixture
def gui():
  params = Params(SoftwareMenu=0, UpdaterState='idle', LastUpdateTime=datetime.datetime(2026, 11, 15))
  ui = NS(params=params, offroad=True)
  ui.is_offroad = lambda: ui.offroad
  ui.is_onroad = lambda: not ui.offroad
  widgets, signals = [], []

  class Widget:
    def show_event(self):
      pass

  class Dialog:
    def __init__(self, title, choices, current, callback):
      self.selection = current
      self.callback = callback
      self.choices = choices

  scope = {
    'ui_state': ui,
    'Widget': Widget,
    'ListItem': Item,
    'text_item': Item,
    'button_item': Item,
    'Scroller': lambda *a, **kw: NS(show_event=lambda: None),
    'tr': lambda x: x,
    'gui_app': NS(push_widget=widgets.append),
    'MultiOptionDialog': Dialog,
    'ConfirmDialog': Dialog,
    'DialogResult': NS(CONFIRM=1, CANCEL=0),
    'datetime': datetime,
    'time': time,
    'os': NS(system=signals.append),
    'UPDATED_TIMEOUT': 30,
    'STATE_TO_DISPLAY_TEXT': {},
    'REQUEST_KEY': manual.REQUEST_KEY,
    'UserRequest': manual.UserRequest,
    'pending_request': manual.pending_request,
    'finish_request': manual.finish_request,
    'system_time_valid': lambda: True,
    'trn': lambda one, many, n: one if n == 1 else many,
  }
  tree = ast.parse((SOURCE / 'openpilot/selfdrive/ui/layouts/settings/software.py').read_text())
  cls = next(x for x in tree.body if isinstance(x, ast.ClassDef) and x.name == 'SoftwareLayout')
  ago = next(x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name == 'time_ago')
  exec(compile(ast.Module(body=[ago, cls], type_ignores=[]), 'software.py', 'exec'), scope)
  return NS(menu=scope['SoftwareLayout'](), params=params, ui=ui, widgets=widgets, signals=signals, scope=scope)


def git(repo, *args):
  return subprocess.run(['git', *args], cwd=repo, check=True, text=True, capture_output=True).stdout.strip()


@pytest.fixture
def updater(tmp_path, gui, monkeypatch):
  monkeypatch.setenv('GIT_CONFIG_GLOBAL', os.devnull)
  monkeypatch.setenv('GIT_CONFIG_NOSYSTEM', '1')
  seed, remote, base = (tmp_path / name for name in ('seed', 'remote.git', 'device'))
  git(tmp_path, 'init', '-b', 'c3-pht-porter', str(seed))
  git(seed, 'config', 'user.name', 'Branch regression')
  git(seed, 'config', 'user.email', 'test@example.invalid')
  (seed / 'menu.txt').write_text('porter')
  git(seed, 'add', '.')
  git(seed, 'commit', '-qm', 'porter')
  git(seed, 'checkout', '--orphan', 'c3-pht')
  (seed / 'menu.txt').write_text('original carrot')
  git(seed, 'add', '.')
  git(seed, 'commit', '-qm', 'unrelated original')
  git(seed, 'branch', 'c3-pht-ioniq')
  git(tmp_path, 'clone', '--bare', str(seed), str(remote))
  git(tmp_path, 'clone', '--depth=1', '--single-branch', '--branch', 'c3-pht-porter', remote.as_uri(), str(base))
  git(base, 'switch', '-c', 'web/origin/c3-pht-porter', '--track', 'origin/c3-pht-porter')
  merged, final = tmp_path / 'merged', tmp_path / 'finalized'
  params = gui.params
  scope = {
    'os': os,
    're': __import__('re'),
    'datetime': datetime,
    'subprocess': subprocess,
    'shutil': shutil,
    'signal': NS(SIGHUP=signal.SIGHUP, SIGUSR1=signal.SIGUSR1, signal=lambda *a: None),
    'fcntl': __import__('fcntl'),
    'time': time,
    'threading': threading,
    'defaultdict': defaultdict,
    'Path': Path,
    'Params': lambda: params,
    'update_lock': nullcontext,
    'BASEDIR': str(base),
    'OVERLAY_MERGED': str(merged),
    'FINALIZED': str(final),
    'STAGING_ROOT': str(tmp_path),
    'LOCK_FILE': str(tmp_path / 'overlay.lock'),
    'OVERLAY_INIT': tmp_path / 'overlay_init',
    'AGNOS': False,
    'HARDWARE': NS(get_device_type=lambda: 'tici'),
    'cloudlog': NS(info=lambda *a, **kw: None, warning=lambda *a, **kw: None, exception=lambda *a, **kw: None, event=lambda *a, **kw: None),
    'psutil': NS(Process=lambda: NS(), LINUX=False),
    'system_time_valid': lambda: True,
    'get_build_metadata': lambda: NS(tested_channel=False),
    'set_offroad_alert': lambda *a, **kw: None,
    'parse_release_notes': lambda path: b'',
    'UserRequest': manual.UserRequest,
    'pending_request': manual.pending_request,
    'finish_request': manual.finish_request,
    'HOURS_NO_CONNECTIVITY_MAX': 2700,
    'ROUTES_NO_CONNECTIVITY_MAX': 8400,
    'HOURS_NO_CONNECTIVITY_PROMPT': 2300,
    'ROUTES_NO_CONNECTIVITY_PROMPT': 8000,
  }
  calls = []

  def run(args, cwd=None):
    calls.append(args[:])
    return process.run(args, cwd)

  scope['run'] = run

  def consistent(enabled):
    marker = final / '.overlay_consistent'
    if enabled:
      marker.touch()
    else:
      marker.unlink(missing_ok=True)

  scope['set_consistent_flag'] = consistent

  def init_overlay():
    if not merged.exists():
      shutil.copytree(base, merged)

  scope['init_overlay'] = init_overlay
  tree = ast.parse((SOURCE / 'openpilot/system/updated/updated.py').read_text())
  selected = [
    x
    for x in tree.body
    if isinstance(x, (ast.ClassDef, ast.FunctionDef))
    and x.name in ('Updater', 'WaitTimeHelper', 'main', 'write_time_to_param', 'setup_git_options', 'finalize_update')
  ]
  exec(compile(ast.Module(body=selected, type_ignores=[]), 'updated.py', 'exec'), scope)
  return NS(scope=scope, run=scope['main'], params=params, base=base, seed=seed, remote=remote, merged=merged, final=final, calls=calls, cls=scope['Updater'])


def select(gui, branch):
  gui.params['UpdaterAvailableBranches'] = 'c3-pht-porter,c3-pht,c3-pht-ioniq'
  gui.menu._on_select_branch()
  dialog = gui.widgets[-1]
  dialog.selection = branch
  dialog.callback(gui.scope['DialogResult'].CONFIRM)


def test_check_button_queues_a_cold_updater_without_enabling_background_preference(gui):
  gui.menu.show_event()
  assert manual.pending_request(gui.params) == manual.UserRequest.CHECK
  assert manual.updater_enabled(False, gui.params)
  assert not gui.params['SoftwareMenu']
  assert gui.signals == []  # No pkill signal to a not-yet-running Python process.
  gui.menu._update_state()
  assert gui.menu._download_btn.value == 'Starting updater…'
  assert not gui.menu._branch_btn.enabled


def test_real_branch_switch_from_check_through_download_to_explicit_install(gui, updater):
  select(gui, 'c3-pht')
  assert gui.params['UpdaterTargetBranch'] == 'c3-pht'
  assert manual.updater_enabled(False, gui.params)
  updater.run()
  assert not manual.updater_enabled(False, gui.params)
  gui.menu._update_state()
  assert gui.menu._download_btn.text == 'DOWNLOAD'
  assert not gui.params.get_bool('DoReboot')
  gui.menu._on_download_update()
  assert manual.pending_request(gui.params) == manual.UserRequest.FETCH
  updater.run()
  assert (updater.base / 'menu.txt').read_text() == 'porter'  # Live checkout untouched.
  assert (updater.final / 'menu.txt').read_text() == 'original carrot'
  assert git(updater.final, 'branch', '--show-current') == 'c3-pht'
  assert git(updater.final, 'rev-parse', 'HEAD') == git(updater.seed, 'rev-parse', 'c3-pht')
  assert gui.params.get_bool('UpdateAvailable')
  assert not gui.params.get_bool('DoReboot')
  gui.menu._update_state()
  assert gui.menu._install_btn.visible
  assert any(a[:4] == ['git', 'fetch', '--depth=1', '--no-tags'] for a in updater.calls)
  # Rechecking a downloaded update must preserve its ready-to-install state.
  gui.menu._request_update(manual.UserRequest.CHECK)
  updater.run()
  assert gui.params.get_bool('UpdateAvailable')
  gui.menu._on_install_update()
  assert gui.params.get_bool('DoReboot')
  assert not gui.params['SoftwareMenu']


def test_default_target_resolves_the_real_remote_branch_of_web_local_alias(gui, updater):
  gui.params.remove('UpdaterTargetBranch')
  assert updater.cls().target_branch == 'c3-pht-porter'


@pytest.mark.parametrize('reason', ['missing_branch', 'missing_origin', 'overlay_failure', 'invalid_clock'])
def test_failed_check_reports_error_and_never_installs_or_reboots(gui, updater, reason):
  select(gui, 'missing' if reason == 'missing_branch' else 'c3-pht')
  if reason == 'missing_origin':
    git(updater.base, 'remote', 'set-url', 'origin', str(updater.base / 'absent.git'))
  if reason == 'overlay_failure':

    def fail():
      raise RuntimeError('cannot prepare update staging')

    updater.scope['init_overlay'] = fail
  if reason == 'invalid_clock':
    updater.scope['system_time_valid'] = lambda: False
  updater.run()
  assert gui.params['UpdateFailedCount'] > 0
  assert gui.params['LastUpdateException']
  assert manual.pending_request(gui.params) == manual.UserRequest.NONE
  assert not manual.updater_enabled(False, gui.params)
  assert not gui.params.get_bool('UpdateAvailable')
  gui.menu._update_state()
  assert gui.menu._download_btn.value == 'failed to check for update'
  assert gui.menu._download_btn.description
  gui.menu._on_install_update()
  assert not gui.params.get_bool('DoReboot')


def test_old_download_cannot_be_installed_after_remote_commit_changes(gui, updater):
  select(gui, 'c3-pht')
  updater.run()
  gui.menu._on_download_update()
  updater.run()
  assert gui.params.get_bool('UpdateAvailable')
  (updater.seed / 'menu.txt').write_text('newer original')
  git(updater.seed, 'commit', '-qam', 'newer')
  git(updater.seed, 'push', str(updater.remote), 'c3-pht')
  gui.menu._request_update(manual.UserRequest.CHECK)
  updater.run()
  assert not gui.params.get_bool('UpdateAvailable')
  assert gui.params.get_bool('UpdaterFetchAvailable')
  gui.menu._on_install_update()
  assert not gui.params.get_bool('DoReboot')


@pytest.mark.parametrize('disabled,onroad', [(True, False), (False, True), (True, True)])
def test_requests_and_install_are_rejected_when_disabled_or_onroad(gui, disabled, onroad):
  gui.params['DisableUpdates'] = disabled
  gui.ui.offroad = not onroad
  gui.menu.show_event()
  gui.menu._on_download_update()
  gui.menu._on_select_branch()
  assert not manual.pending_request(gui.params)
  assert not gui.widgets
  assert not manual.updater_enabled(onroad, gui.params)
  gui.params['UpdateAvailable'] = True
  gui.menu._on_install_update()
  assert not gui.params.get_bool('DoReboot')


def test_target_is_written_before_waking_the_updater(gui, monkeypatch):
  original = gui.params.put_int

  def publish(key, value):
    if key == manual.REQUEST_KEY:
      assert gui.params.get('UpdaterTargetBranch') == 'c3-pht'
    original(key, value)

  monkeypatch.setattr(gui.params, 'put_int', publish)
  select(gui, 'c3-pht')


def test_rechecking_a_ready_download_never_opens_a_background_git_window(gui, monkeypatch):
  gui.params['UpdateAvailable'] = True
  original = gui.params.put_bool

  def publish(key, value):
    if key == 'UpdateAvailable' and not value:
      assert manual.pending_request(gui.params) == manual.UserRequest.CHECK
    original(key, value)

  monkeypatch.setattr(gui.params, 'put_bool', publish)
  gui.menu._request_update(manual.UserRequest.CHECK)


def test_manual_origin_advertisement_does_not_follow_a_different_tracking_remote(gui, updater):
  git(updater.base, 'remote', 'add', 'old-fork', str(updater.base / 'missing.git'))
  git(updater.base, 'config', 'branch.web/origin/c3-pht-porter.remote', 'old-fork')
  select(gui, 'c3-pht')
  updater.run()
  assert gui.params.get_bool('UpdaterFetchAvailable')
  assert ['git', 'ls-remote', '--heads', 'origin'] in updater.calls


def test_background_setting_still_controls_idle_daemon_and_disable_policy_wins(gui):
  gui.params['SoftwareMenu'] = 1
  assert manual.updater_enabled(False, gui.params)
  gui.params['DisableUpdates'] = True
  gui.params.put_int(manual.REQUEST_KEY, manual.UserRequest.CHECK)
  assert not manual.updater_enabled(False, gui.params)


def test_branch_dialog_rechecks_offroad_permission_when_confirmed(gui):
  gui.params['UpdaterAvailableBranches'] = 'c3-pht'
  gui.menu._on_select_branch()
  dialog = gui.widgets[-1]
  dialog.selection = 'c3-pht'
  gui.ui.offroad = False
  dialog.callback(gui.scope['DialogResult'].CONFIRM)
  assert not manual.pending_request(gui.params)
  assert not gui.params.get('UpdaterTargetBranch')


def test_startup_timeout_exposes_failure_and_can_be_retried(gui):
  gui.menu._on_download_update()
  gui.menu._waiting_start_ts = time.monotonic() - 31
  gui.menu._update_state()
  assert not manual.pending_request(gui.params)
  assert gui.menu._download_btn.value == 'Updater did not start. Try CHECK again.'
  gui.menu._on_download_update()
  assert manual.pending_request(gui.params) == manual.UserRequest.CHECK


def test_background_sleep_observes_request_without_an_os_signal(gui, updater):
  helper = updater.scope['WaitTimeHelper'](gui.params)
  timer = threading.Timer(0.02, lambda: gui.params.put_int(manual.REQUEST_KEY, manual.UserRequest.FETCH))
  timer.start()
  try:
    helper.sleep(0.2)
  finally:
    timer.join()
  assert helper.user_request == manual.UserRequest.FETCH
  helper.finish_manual_request()
  assert not manual.pending_request(gui.params)


def test_finishing_check_does_not_clear_a_new_download_request(gui):
  gui.params.put_int(manual.REQUEST_KEY, manual.UserRequest.FETCH)
  manual.finish_request(gui.params, manual.UserRequest.CHECK)
  assert manual.pending_request(gui.params) == manual.UserRequest.FETCH


def test_manager_actual_predicate_allows_manual_work_and_still_stops_onroad(gui):
  tree = ast.parse((SOURCE / 'openpilot/system/manager/process_config.py').read_text())
  fn = next(x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name == 'enable_updated')
  scope = {'Params': Params, 'car': NS(CarParams=object), 'updater_enabled': manual.updater_enabled}
  exec(compile(ast.Module(body=[fn], type_ignores=[]), 'process_config.py', 'exec'), scope)
  gui.params.put_int(manual.REQUEST_KEY, manual.UserRequest.CHECK)
  assert scope['enable_updated'](False, gui.params, None)
  assert not scope['enable_updated'](True, gui.params, None)


def test_request_and_busy_state_are_cleared_on_manager_start_and_onroad_transition():
  header = (SOURCE / 'openpilot/common/params_keys.h').read_text()
  for name in ('UpdaterManualRequest', 'UpdaterState'):
    line = next(x for x in header.splitlines() if '"' + name + '"' in x)
    assert 'CLEAR_ON_MANAGER_START' in line and 'CLEAR_ON_ONROAD_TRANSITION' in line


@pytest.mark.parametrize('kind', ['queued', 'checking', 'downloaded', 'idle'])
def test_native_activity_protects_the_staging_timestamp(gui, kind):
  if kind == 'queued':
    gui.params.put_int(manual.REQUEST_KEY, manual.UserRequest.CHECK)
  if kind == 'checking':
    gui.params['UpdaterState'] = 'checking...'
  if kind == 'downloaded':
    gui.params['UpdateAvailable'] = True
  assert manual.native_update_active(gui.params) == (kind != 'idle')


def test_native_transaction_waits_for_existing_web_git_and_protects_children(tmp_path, monkeypatch):
  from openpilot.common import repo_update

  lock = tmp_path / 'update.lock'
  monkeypatch.setattr(repo_update, 'LOCK_PATH', str(lock))
  child = subprocess.Popen(['flock', str(lock), 'sh', '-c', 'echo locked; sleep 0.3'], stdout=subprocess.PIPE, text=True)
  assert child.stdout.readline().strip() == 'locked'
  start = time.monotonic()
  with manual.update_lock(timeout=2):
    assert time.monotonic() - start >= 0.2
    assert subprocess.run(['flock', '-n', str(lock), 'true']).returncode != 0
    assert repo_update.child_lock_kwargs().get('pass_fds')
    fd = repo_update.child_lock_kwargs()['pass_fds'][0]
    inherited = process.run([sys.executable, '-c', f'import os; print(os.fstat({fd}).st_ino)'])
    assert int(inherited.strip()) == lock.stat().st_ino
  child.wait()
  assert subprocess.run(['flock', '-n', str(lock), 'true']).returncode == 0
