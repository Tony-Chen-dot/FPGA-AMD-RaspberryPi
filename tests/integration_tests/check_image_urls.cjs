const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

let component;
const app = { use() { return this; }, mount() {} };
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../dashboard/web/js/dashboard.js'), 'utf8'), {
  URL, URLSearchParams,
  window: {
    location: { origin: 'http://testserver', search: '' },
    addEventListener(_event, callback) { callback(); },
  },
  Vue: { createApp(options) { component = options; return app; } },
  Pinia: { createPinia() {}, defineStore() {} },
});

const cacheBust = component.methods.cacheBust;
assert.equal(cacheBust('', 'frame'), '');
for (const input of ['/api/frame/sample', '/api/frame/sample?line_id=3', '/api/frame/sample?line_id=3&v=old#preview']) {
  const output = new URL(cacheBust(input, 'frame + 1'));
  const original = new URL(input, 'http://testserver');
  assert.equal(output.searchParams.get('line_id'), original.searchParams.get('line_id'));
  assert.equal(output.searchParams.get('v'), 'frame + 1');
  assert.equal(output.searchParams.getAll('v').length, 1);
  assert.equal(output.hash, original.hash);
}
if (process.argv[2]) process.stdout.write(cacheBust(process.argv[2], 'sample'));
