"""Load real Git tools without importing the vehicle-wide features package."""
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace


def load_branch_tools():
  root = Path(__file__).resolve().parents[1]
  base = '_carrot_branch_tests.server'
  for name, directory in (('_carrot_branch_tests', root.parent), (base, root),
                          (base + '.features', root / 'features'), (base + '.features.tools', root / 'features/tools')):
    if name not in sys.modules:
      package = ModuleType(name)
      package.__path__ = [str(directory)]
      sys.modules[name] = package
  loaded = {}
  for suffix, path in (('config', root / 'config.py'), ('features.tools.jobs', root / 'features/tools/jobs.py'),
                       ('features.tools.branches', root / 'features/tools/branches.py')):
    name = f'{base}.{suffix}'
    if name not in sys.modules:
      spec = importlib.util.spec_from_file_location(name, path)
      module = importlib.util.module_from_spec(spec)
      sys.modules[name] = module
      spec.loader.exec_module(module)
    loaded[suffix.rsplit('.', 1)[-1]] = sys.modules[name]
  return SimpleNamespace(**loaded)
