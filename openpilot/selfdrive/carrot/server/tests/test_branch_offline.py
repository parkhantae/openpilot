"""Real Git refs/worktrees through both production Web branch dispatch paths."""
import ast
import asyncio
import json
import os
from pathlib import Path
import shlex
import subprocess
import traceback
from types import SimpleNamespace as NS

import pytest
from aiohttp import web

from openpilot.selfdrive.carrot.server.tests.branch_test_support import load_branch_tools

_tools = load_branch_tools()
branch_jobs = _tools.jobs
checkout_branch, list_branches = _tools.branches.checkout_branch, _tools.branches.list_branches


def git(repo, *args):
  return subprocess.run(['git', *args], cwd=repo, text=True, capture_output=True, check=True).stdout.strip()


@pytest.fixture
def device(tmp_path, monkeypatch):
  monkeypatch.setenv('GIT_CONFIG_GLOBAL', os.devnull)
  monkeypatch.setenv('GIT_CONFIG_NOSYSTEM', '1')
  repo = tmp_path / 'device'
  repo.mkdir()
  git(repo, 'init', '-b', 'c3-pht-porter')
  git(repo, 'config', 'user.name', 'Branch test')
  git(repo, 'config', 'user.email', 'test@example.invalid')
  (repo / 'version.txt').write_text('porter\n')
  git(repo, 'add', 'version.txt')
  git(repo, 'commit', '-qm', 'Porter')
  git(repo, 'switch', '-c', 'c3-pht')
  (repo / 'version.txt').write_text('ioniq\n')
  git(repo, 'commit', '-qam', 'Ioniq')
  head = git(repo, 'rev-parse', 'HEAD')
  git(repo, 'update-ref', 'refs/remotes/origin/c3-pht', head)
  git(repo, 'remote', 'add', 'origin', 'https://offline.invalid/openpilot.git')
  git(repo, 'branch', '--set-upstream-to=origin/c3-pht', 'c3-pht')
  git(repo, 'switch', 'c3-pht-porter')
  return repo


def dispatcher(repo, *, timeout=False, refs_error=False):
  # Execute the unchanged bodies of the production dispatchers without device
  # boot dependencies. Only the /data path and external fetch are substituted.
  source = Path(__file__).resolve().parents[1] / 'features/tools/dispatcher.py'
  tree = ast.parse(source.read_text())
  names = {'_branch_command', '_run_tool_job', '_dispatch_sync'}
  nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
  calls = []

  def run(args, *, cwd=None, **kwargs):
    calls.append(args)
    if args[:2] in (['git', 'fetch'], ['git', 'ls-remote']):
      return subprocess.CompletedProcess(args, 128, '', 'Could not resolve host: offline.invalid')
    if refs_error and args[:2] == ['git', 'for-each-ref']:
      return subprocess.CompletedProcess(args, 128, '', 'fatal: invalid ref database')
    return subprocess.run(args, cwd=repo if cwd == '/data/openpilot' else cwd, **kwargs)

  async def capture(args, *, cwd, timeout):  # noqa: ASYNC109 - production exec adapter
    if args[:2] == ['git', 'ls-remote']:
      assert timeout == 8
      if globals_timeout:
        calls.append(args)
        raise TimeoutError()
    p = run(args, cwd=cwd, text=True, capture_output=True)
    return p.returncode, (p.stdout + p.stderr).strip()

  def append(job, text):
    job['log'] = job.get('log', '') + str(text)

  async def stream(job, args, *, cwd, timeout):  # noqa: ASYNC109 - production exec adapter
    if args[:2] == ['git', 'fetch'] and globals_timeout:
      calls.append(args)
      raise TimeoutError()
    rc, out = await capture(args, cwd=cwd, timeout=timeout)
    append(job, out)
    return rc

  globals_timeout = timeout

  async def process(args, *, cwd, timeout):  # noqa: ASYNC109 - production exec adapter
    return await capture(args, cwd=cwd, timeout=timeout)

  def finish(job, *, ok, result, **kw):
    job.update(ok=ok, result=result)

  helpers = NS(capture_exec=capture, stream_exec=stream, append=append, finish=finish,
               progress=lambda *a, **kw: None, result_from_log=lambda job, rc, **kw: {'ok': rc == 0, 'out': job['log']},
               build_branch_items=branch_jobs.build_branch_items, parse_remote_urls=branch_jobs.parse_remote_urls,
               get_branch_prefix=lambda: 'c3')
  env = {'asyncio': asyncio, 'web': web, 'jobs': helpers, 'run_process': process, 'BRANCH_LIST_FETCH_TIMEOUT': 8,
         'subprocess': NS(run=run), 'child_lock_kwargs': dict, 'shlex': shlex, 'traceback': traceback,
         'normalize_action': lambda a: a, 'validate_action': lambda a: None, 'HARDWARE': NS(get_device_type=lambda: 'tici'),
         'checkout_branch': checkout_branch, 'list_branches': list_branches, 'clear_git_status_cache': lambda: None}
  future = ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0)
  exec(compile(ast.fix_missing_locations(ast.Module(body=[future, *nodes], type_ignores=[])), str(source), 'exec'), env)

  def request(mode, action, **body):
    if mode == 'stream':
      job = {'action': action, 'payload': body, 'log': ''}
      asyncio.run(env['_run_tool_job'](job))
      return job['result']
    response = asyncio.run(env['_dispatch_sync'](None, {'action': action, **body}))
    return json.loads(response.body)

  return NS(request=request, calls=calls)


@pytest.mark.parametrize('mode', ['stream', 'sync'])
@pytest.mark.parametrize('timeout', [False, True], ids=['dns-error', 'timeout'])
def test_failed_remote_refresh_still_lists_saved_local_and_remote_branches(device, mode, timeout):
  d = dispatcher(device, timeout=timeout)
  result = d.request(mode, 'git_branch_list')
  assert result['ok']
  assert result['cached'] and not result['fetch_ok']
  assert result['current_branch'] == 'c3-pht-porter'
  assert {'c3-pht', 'origin/c3-pht'} <= set(result['branches'])
  assert 'timed out' in result['fetch'] if timeout else 'Could not resolve host' in result['fetch']


@pytest.mark.parametrize('mode', ['stream', 'sync'])
@pytest.mark.parametrize('payload', [
  {'branch': 'c3-pht', 'kind': 'local', 'name': 'c3-pht'},
  {'branch': 'origin/c3-pht', 'kind': 'remote', 'remote': 'origin', 'name': 'c3-pht'},
  {'branch': 'origin/c3-pht'}, {'branch': 'c3-pht'},
])
def test_existing_local_checkout_has_no_network_dependency(device, mode, payload):
  d = dispatcher(device)
  expected = git(device, 'rev-parse', 'c3-pht')
  (device / 'keep.txt').write_text('untracked driver file\n')
  assert d.request(mode, 'git_checkout', **payload)['ok']
  assert not any(c[:2] == ['git', 'fetch'] for c in d.calls)
  assert git(device, 'branch', '--show-current') == 'c3-pht'
  assert git(device, 'rev-parse', 'HEAD') == expected
  assert (device / 'version.txt').read_text() == 'ioniq\n'
  assert (device / 'keep.txt').read_text() == 'untracked driver file\n'


@pytest.mark.parametrize('mode', ['stream', 'sync'])
def test_local_modifications_still_block_checkout_without_reset_or_force(device, mode):
  (device / 'version.txt').write_text('driver edit\n')
  d = dispatcher(device)
  result = d.request(mode, 'git_checkout', branch='c3-pht', kind='local', name='c3-pht')
  assert not result['ok']
  assert 'would be overwritten' in result['out']
  assert git(device, 'branch', '--show-current') == 'c3-pht-porter'
  assert (device / 'version.txt').read_text() == 'driver edit\n'


@pytest.mark.parametrize('mode', ['stream', 'sync'])
def test_new_branch_without_network_is_not_created_from_stale_remote_cache(device, mode):
  git(device, 'branch', '-D', 'c3-pht')
  d = dispatcher(device)
  result = d.request(mode, 'git_checkout', branch='origin/c3-pht', kind='remote', name='c3-pht', remote='origin')
  assert not result['ok']
  assert 'Could not resolve host' in result['out']
  assert git(device, 'branch', '--show-current') == 'c3-pht-porter'
  assert not git(device, 'branch', '--list', 'c3-pht')


@pytest.mark.parametrize('mode', ['stream', 'sync'])
def test_invalid_local_refs_are_not_reported_as_a_successful_cached_list(device, mode):
  d = dispatcher(device, refs_error=True)
  result = d.request(mode, 'git_branch_list')
  assert not result['ok']
