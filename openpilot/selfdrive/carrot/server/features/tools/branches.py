"""Repository-aware branch discovery and checkout; callers hold the repo lock."""
import asyncio
from urllib.parse import urlsplit

from .jobs import build_branch_items, parse_remote_urls

REPOSITORIES = ('ajouatom', 'parkhantae')
DISCOVERY_TIMEOUT = 8


def repository_owner(url):
  if url.startswith('git@github.com:'):
    path = url.split(':', 1)[1]
  else:
    parsed = urlsplit(url)
    if parsed.hostname != 'github.com':
      return None
    path = parsed.path.lstrip('/')
  parts = path.rstrip('/').removesuffix('.git').split('/')
  return parts[0].lower() if len(parts) == 2 and parts[1].lower() == 'openpilot' else None


async def configured_remotes(run):
  rc, output = await run(['git', 'remote', '-v'])
  if rc:
    raise RuntimeError(output)
  urls = parse_remote_urls(output)
  selected = []
  for owner in REPOSITORIES:
    existing = next((name for name, url in urls.items() if repository_owner(url) == owner), None)
    if existing is None:
      name, suffix = owner, 1
      while name in urls:
        suffix += 1
        name = f'{owner}-openpilot{suffix if suffix > 2 else ""}'
      url = f'https://github.com/{owner}/openpilot.git'
      rc, output = await run(['git', 'remote', 'add', name, url])
      if rc:
        raise RuntimeError(output)
      urls[name] = url
      existing = name
    selected.append(existing)
  # Keep other repositories, while showing one group per requested repository.
  # Existing remote names and URLs are never overwritten or removed.
  selected.extend(name for name, url in urls.items() if repository_owner(url) not in REPOSITORIES)
  return urls, selected


async def list_branches(run):
  urls, remotes = await configured_remotes(run)
  rc, local = await run(['git', 'for-each-ref', '--format=%(refname:short)', 'refs/heads'])
  rc_remote, cached = await run(['git', 'for-each-ref', '--format=%(refname:short)', 'refs/remotes'])
  if rc or rc_remote:
    raise RuntimeError(local if rc else cached)

  async def discover(remote):
    code, output = await run(['git', 'ls-remote', '--heads', remote], timeout=DISCOVERY_TIMEOUT)
    if code == 0:
      refs = [f'{remote}/{fields[1][11:]}' for line in output.splitlines()
              if len(fields := line.split()) == 2 and fields[1].startswith('refs/heads/')]
    else:
      refs = [line for line in cached.splitlines() if line.startswith(f'{remote}/')]
    return remote, code, output, refs

  # List all branch names without fetching their histories or relying on a
  # possibly single-branch fetch refspec. Remotes have independent deadlines.
  discovered = await asyncio.gather(*(discover(remote) for remote in remotes))
  refs = '\n'.join(ref for _, _, _, entries in discovered for ref in entries)
  items = build_branch_items(local, refs, remotes)
  rc, current = await run(['git', 'branch', '--show-current'])
  failed = {remote: output for remote, code, output, _ in discovered if code}
  return {
    'ok': True, 'branch_items': items, 'branches': sorted({item['ref'] for item in items}),
    'current_branch': current.strip() if rc == 0 else '', 'remotes': list(urls), 'remote_urls': urls,
    'fetch_ok': not failed, 'cached': bool(failed), 'refresh_errors': failed,
    'fetch': '\n'.join(f'{remote}: {output}' for remote, _, output, _ in discovered if output),
    'summary_key': 'git_result_branch_list_done', 'summary_vars': {'count': len(items)},
  }


async def checkout_branch(run, body):
  branch = str(body.get('branch') or '').strip()
  kind = str(body.get('kind') or '').strip()
  name = str(body.get('name') or branch).strip()
  remote = str(body.get('remote') or '').strip()
  rc, output = await run(['git', 'remote'])
  if rc:
    return {'ok': False, 'out': output, 'rc': rc}
  remotes = output.split()
  if kind == 'remote':
    if not remote or remote not in remotes or not body.get('name'):
      return {'ok': False, 'error': 'Unknown remote or missing branch name'}
  elif kind != 'local':
    matched = next((r for r in sorted(remotes, key=len, reverse=True) if branch.startswith(f'{r}/')), None)
    if matched:
      remote, name = matched, branch[len(matched) + 1:]
    else:
      rc, _ = await run(['git', 'show-ref', '--verify', '--quiet', f'refs/heads/{name}'])
      remote = '' if rc == 0 else 'origin'
  else:
    remote = ''
  rc, output = await run(['git', 'check-ref-format', '--branch', name])
  if rc or name.startswith('-') or output.strip() != name:
    return {'ok': False, 'error': 'Invalid branch name', 'out': output}

  local, exists = name, False
  if remote:
    if remote not in remotes:
      return {'ok': False, 'error': f'Unknown remote: {remote}'}
    # A same-named local branch may track the other fork. Keep that branch and
    # its commits, using a separate local name for the selected repository.
    for attempt in range(100):
      rc, _ = await run(['git', 'show-ref', '--verify', '--quiet', f'refs/heads/{local}'])
      if rc:
        break
      _, owner = await run(['git', 'config', '--get', f'branch.{local}.remote'])
      _, merge = await run(['git', 'config', '--get', f'branch.{local}.merge'])
      if owner.strip() == remote and merge.strip() == f'refs/heads/{name}':
        exists = True
        break
      local = f'web/{remote}/{name}{f"-{attempt + 1}" if attempt else ""}'
    else:
      return {'ok': False, 'error': 'No unused local branch name for this repository'}
    if not exists:
      target = f'refs/remotes/{remote}/{name}'
      rc, output = await run(['git', 'fetch', '--no-tags', '--no-recurse-submodules', remote,
                              f'+refs/heads/{name}:{target}'], timeout=180)
      if rc:
        return {'ok': False, 'out': output, 'rc': rc}
      _, specs = await run(['git', 'config', '--get-all', f'remote.{remote}.fetch'])
      spec = f'+refs/heads/{name}:{target}'
      if f'+refs/heads/*:refs/remotes/{remote}/*' not in specs.splitlines() and spec not in specs.splitlines():
        rc, output = await run(['git', 'config', '--add', f'remote.{remote}.fetch', spec])
        if rc:
          return {'ok': False, 'out': output, 'rc': rc}
      rc, output = await run(['git', 'switch', '-c', local, '--track', target])
    else:
      rc, output = await run(['git', 'switch', '--', local])
  else:
    rc, output = await run(['git', 'switch', '--', local])
  return {'ok': rc == 0, 'rc': rc, 'out': output, 'empty_output': not output,
          'summary_key': 'git_result_checkout_done', 'summary_vars': {'branch': local}}
