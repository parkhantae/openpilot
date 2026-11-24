import asyncio
import os
import subprocess
from types import SimpleNamespace as NS

import pytest

from openpilot.selfdrive.carrot.server.tests.branch_test_support import load_branch_tools

_branches = load_branch_tools().branches
checkout_branch, list_branches, repository_owner = _branches.checkout_branch, _branches.list_branches, _branches.repository_owner


def git(repo, *args):
  return subprocess.run(['git', *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repos(tmp_path, monkeypatch):
  monkeypatch.setenv('GIT_CONFIG_GLOBAL', os.devnull)
  monkeypatch.setenv('GIT_CONFIG_NOSYSTEM', '1')
  seed = tmp_path / 'seed'
  seed.mkdir()
  git(seed, 'init', '-b', 'carrot-wip')
  git(seed, 'config', 'user.name', 'Branch test')
  git(seed, 'config', 'user.email', 'test@example.invalid')
  (seed / 'version.txt').write_text('ajouatom\n')
  git(seed, 'add', '.')
  git(seed, 'commit', '-qm', 'upstream')
  git(seed, 'branch', 'nested/topic')
  a = tmp_path / 'ajouatom.git'
  git(tmp_path, 'clone', '--bare', str(seed), str(a))
  upstream_head = git(seed, 'rev-parse', 'HEAD')
  (seed / 'version.txt').write_text('parkhantae\n')
  git(seed, 'commit', '-qam', 'fork')
  git(seed, 'branch', 'c3-pht-porter')
  b = tmp_path / 'parkhantae.git'
  git(tmp_path, 'clone', '--bare', str(seed), str(b))
  fork_head = git(seed, 'rev-parse', 'HEAD')
  device = tmp_path / 'device'
  git(tmp_path, 'clone', '--depth=1', '--single-branch', '--branch', 'c3-pht-porter', b.as_uri(), str(device))
  git(device, 'remote', 'set-url', 'origin', 'https://github.com/parkhantae/openpilot.git')
  calls, unavailable = [], set()
  bare = {'ajouatom': a, 'parkhantae': b}

  async def run(args, *, timeout=15):  # noqa: ASYNC109 - subprocess adapter
    calls.append((args.copy(), timeout))
    command = args.copy()
    if args[:2] == ['git', 'ls-remote'] or args[:2] == ['git', 'fetch']:
      index = 3 if args[1] == 'ls-remote' else 4
      remote = args[index]
      owner = repository_owner(git(device, 'remote', 'get-url', remote))
      if owner in unavailable:
        return 124, 'remote discovery timed out'
      assert owner in bare, command
      command[index] = str(bare[owner])
    result = subprocess.run(command, cwd=device, capture_output=True, text=True)  # noqa: ASYNC221 - local Git fixture
    return result.returncode, (result.stdout + result.stderr).strip()

  async def choose(remote, name='carrot-wip'):
    return await checkout_branch(run, {'kind': 'remote', 'remote': remote, 'name': name, 'branch': f'{remote}/{name}'})

  return NS(device=device, run=run, choose=choose, calls=calls, unavailable=unavailable,
            upstream_head=upstream_head, fork_head=fork_head)


def test_lists_all_branches_from_both_repositories_despite_single_branch_clone(repos):
  before = git(repos.device, 'config', '--get-all', 'remote.origin.fetch')
  result = asyncio.run(list_branches(repos.run))
  assert result['ok'] and result['fetch_ok']
  assert {'ajouatom/carrot-wip', 'origin/carrot-wip', 'ajouatom/nested/topic', 'origin/nested/topic'} <= set(result['branches'])
  assert result['remote_urls']['origin'] == 'https://github.com/parkhantae/openpilot.git'
  assert git(repos.device, 'config', '--get-all', 'remote.origin.fetch') == before
  assert not any(args[1] == 'fetch' for args, _ in repos.calls)
  assert all(timeout == 8 for args, timeout in repos.calls if args[1] == 'ls-remote')
  names = git(repos.device, 'remote')
  asyncio.run(list_branches(repos.run))
  assert git(repos.device, 'remote') == names  # Idempotent remote registration.


def test_same_named_branches_select_exact_repository_and_preserve_both_histories(repos):
  asyncio.run(list_branches(repos.run))
  result = asyncio.run(repos.choose('origin'))
  assert result['ok'], result
  assert git(repos.device, 'rev-parse', 'HEAD') == repos.fork_head
  assert git(repos.device, 'rev-parse', '--abbrev-ref', '@{upstream}') == 'origin/carrot-wip'
  result = asyncio.run(repos.choose('ajouatom'))
  assert result['ok'], result
  assert result['summary_vars']['branch'] == 'web/ajouatom/carrot-wip'
  assert git(repos.device, 'rev-parse', 'HEAD') == repos.upstream_head
  assert git(repos.device, 'rev-parse', 'carrot-wip') == repos.fork_head
  assert git(repos.device, 'rev-parse', '--abbrev-ref', '@{upstream}') == 'ajouatom/carrot-wip'
  repos.calls.clear()
  repos.unavailable.update(('ajouatom', 'parkhantae'))
  assert asyncio.run(repos.choose('origin'))['ok']
  assert git(repos.device, 'rev-parse', 'HEAD') == repos.fork_head
  assert asyncio.run(repos.choose('ajouatom'))['ok']
  assert git(repos.device, 'rev-parse', 'HEAD') == repos.upstream_head
  assert not any(args[1] == 'fetch' for args, _ in repos.calls)


def test_single_branch_refspec_gets_selected_upstream_mapping_for_future_pull(repos):
  result = asyncio.run(repos.choose('origin', 'nested/topic'))
  assert result['ok'], result
  assert git(repos.device, 'config', 'branch.nested/topic.remote') == 'origin'
  assert git(repos.device, 'config', 'branch.nested/topic.merge') == 'refs/heads/nested/topic'
  assert git(repos.device, 'rev-parse', '--abbrev-ref', '@{upstream}') == 'origin/nested/topic'
  fetches = [args for args, _ in repos.calls if args[1] == 'fetch']
  assert len(fetches) == 1
  assert fetches[0][-1] == '+refs/heads/nested/topic:refs/remotes/origin/nested/topic'


def test_remote_alias_collision_and_duplicate_repository_aliases_are_preserved(repos):
  git(repos.device, 'remote', 'add', 'ajouatom', 'https://example.invalid/other.git')
  git(repos.device, 'remote', 'add', 'parkhantae', 'git@github.com:parkhantae/openpilot.git')
  repos.unavailable.update(('ajouatom',))
  # Keep this unrelated existing remote offline without contacting it.
  original = repos.run

  async def run(args, **kw):
    if args[:4] == ['git', 'ls-remote', '--heads', 'ajouatom']:
      return 128, 'unrelated remote offline'
    return await original(args, **kw)

  result = asyncio.run(list_branches(run))
  assert 'ajouatom-openpilot' in result['remotes']
  assert git(repos.device, 'remote', 'get-url', 'ajouatom') == 'https://example.invalid/other.git'
  assert git(repos.device, 'remote', 'get-url', 'origin') == 'https://github.com/parkhantae/openpilot.git'
  assert not any(item['ref'].startswith('parkhantae/') for item in result['branch_items'])
  assert 'origin/carrot-wip' in result['branches']


def test_one_failed_repository_keeps_other_live_names_and_failed_repository_cache(repos):
  asyncio.run(list_branches(repos.run))
  assert asyncio.run(repos.choose('ajouatom'))['ok']
  repos.unavailable.add('ajouatom')
  result = asyncio.run(list_branches(repos.run))
  assert result['ok'] and result['cached'] and not result['fetch_ok']
  assert 'ajouatom/carrot-wip' in result['branches']
  assert 'origin/nested/topic' in result['branches']
  assert set(result['refresh_errors']) == {'ajouatom'}


def test_untracked_local_branch_is_not_rebound_or_discarded(repos):
  git(repos.device, 'branch', 'carrot-wip')
  saved = git(repos.device, 'rev-parse', 'carrot-wip')
  asyncio.run(list_branches(repos.run))
  result = asyncio.run(repos.choose('ajouatom'))
  assert result['ok'] and result['summary_vars']['branch'] == 'web/ajouatom/carrot-wip'
  assert git(repos.device, 'rev-parse', 'carrot-wip') == saved


def test_new_checkout_preserves_conflicting_worktree_edits(repos):
  asyncio.run(list_branches(repos.run))
  (repos.device / 'version.txt').write_text('my local edit\n')
  saved = git(repos.device, 'rev-parse', 'HEAD')
  result = asyncio.run(repos.choose('ajouatom'))
  assert not result['ok'] and 'would be overwritten' in result['out']
  assert git(repos.device, 'rev-parse', 'HEAD') == saved
  assert (repos.device / 'version.txt').read_text() == 'my local edit\n'
  assert not git(repos.device, 'branch', '--list', 'carrot-wip')


def test_discovery_starts_both_remotes_without_waiting_for_the_other(repos):
  async def exercise():
    started, ready = set(), asyncio.Event()

    async def run(args, **kw):
      if args[:2] == ['git', 'ls-remote']:
        started.add(args[3])
        if len(started) == 2:
          ready.set()
        await asyncio.wait_for(ready.wait(), .2)
      return await repos.run(args, **kw)

    assert (await list_branches(run))['fetch_ok']
    assert started == {'origin', 'ajouatom'}

  asyncio.run(exercise())


@pytest.mark.parametrize('name', ['--detach', 'HEAD', '../escape', 'bad name', '@{-1}'])
def test_invalid_or_shorthand_names_never_switch_or_fetch(repos, name):
  result = asyncio.run(repos.choose('origin', name))
  assert not result['ok']
  assert git(repos.device, 'branch', '--show-current') == 'c3-pht-porter'
  assert not any(args[1] in ('switch', 'fetch') for args, _ in repos.calls)


@pytest.mark.parametrize('url,owner', [
  ('https://github.com/ajouatom/openpilot.git', 'ajouatom'),
  ('git@github.com:parkhantae/openpilot.git', 'parkhantae'),
  ('ssh://git@github.com/ajouatom/openpilot', 'ajouatom'),
  ('https://example.invalid/ajouatom/openpilot.git', None),
  ('https://github.com/ajouatom/different.git', None),
])
def test_repository_identity_uses_host_and_repository(url, owner):
  assert repository_owner(url) == owner
