import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../js/pages/branch.js', import.meta.url), 'utf8');

for (const originOwner of ['parkhantae', 'ajouatom']) {
  test(`repository groups preserve checkout identity when origin is ${originOwner}`, () => {
    const other = originOwner === 'parkhantae' ? 'ajouatom' : 'parkhantae';
    const context = vm.createContext({
      appBranchPickerBackdrop: null, appBranchPickerClose: null, CURRENT_BRANCH_NAME: 'c3-pht', URL,
    });
    vm.runInContext(source, context);
    const result = {
      remotes: ['origin', 'fork'],
      remote_urls: { origin: `https://github.com/${originOwner}/openpilot.git`, fork: `git@github.com:${other}/openpilot.git` },
      branch_items: ['origin', 'fork'].map(remote => ({ kind: 'remote', remote, name: 'carrot-wip', ref: `${remote}/carrot-wip` })),
    };
    context.syncBranchRemoteContext(result);
    context.BRANCHES = context.normalizeBranchItems(result);
    const groups = context.getBranchGroups();
    assert.equal(groups.length, 2);
    assert.deepEqual(Array.from(groups, g => g.title).sort(), ['ajouatom/openpilot', 'parkhantae/openpilot']);
    for (const group of groups) {
      assert.equal(group.items.length, 1);
      const item = group.items[0];
      const expected = group.title.startsWith(originOwner) ? 'origin' : 'fork';
      assert.equal(item.checkoutPayload.remote, expected);
      assert.equal(item.checkoutPayload.name, 'carrot-wip');
      assert.equal(item.checkoutPayload.branch, `${expected}/carrot-wip`);
    }
  });
}

test('other repositories retain their actual identity', () => {
  const context = vm.createContext({ appBranchPickerBackdrop: null, appBranchPickerClose: null, URL });
  vm.runInContext(source, context);
  assert.equal(context.parseGitHubRepository('https://github.com/parkhantae/hantae.git'), 'parkhantae/hantae');
  assert.equal(context.parseGitHubRepository('https://example.invalid/github.com/parkhantae/openpilot.git'), '');
  assert.equal(context.parseGitHubRepository('ssh://git@github.com/ajouatom/openpilot.git'), 'ajouatom/openpilot');
});
