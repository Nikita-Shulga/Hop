import { readFileSync } from 'node:fs';
import { Script, createContext } from 'node:vm';
import assert from 'node:assert/strict';

for (const name of ['static/index.html', 'static/host.html', 'cloud/public/static/index.html']) {
  const html = readFileSync(name, 'utf8');
  let count = 0;
  for (const match of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)) {
    new Script(match[1], { filename: `${name}:script${++count}` });
  }
  assert.ok(count, `No scripts checked in ${name}`);
  console.log(`${name}: ${count} script(s) parsed`);
}
for (const name of ['static/index.html', 'static/i18n.js']) {
  assert.equal(readFileSync(name, 'utf8'), readFileSync('cloud/public/' + (name.endsWith('.js') ? name : 'static/index.html'), 'utf8'),
               'LAN and cloud viewers must be identical; run node cloud/build.mjs');
}
console.log('LAN/cloud viewer parity: passed');

// Interface text: run static/i18n.js and check both languages have the same keys and placeholders.
const sandbox = { window: {}, document: { documentElement: {} }, Intl };
createContext(sandbox);
new Script(readFileSync('static/i18n.js', 'utf8'), { filename: 'static/i18n.js' }).runInContext(sandbox);
const I18N = sandbox.window.HopI18n;
assert.equal(I18N.lang(), 'en', 'English must be the default language');
const strings = (lang) => {
  I18N.setLang(lang);
  return JSON.parse(readFileSync('static/i18n.js', 'utf8').match(/\/\*STRINGS\*\/([\s\S]*?)\/\*END STRINGS\*\//)[1])[lang];
};
const en = strings('en'), ru = strings('ru');
assert.deepEqual(Object.keys(ru).sort(), Object.keys(en).sort(), 'English and Russian need the same keys');
I18N.setLang('ru');
assert.equal(I18N.t('v.fileCount', { n: 1 }), '1 файл');
assert.equal(I18N.t('v.fileCount', { n: 3 }), '3 файла');
assert.equal(I18N.t('v.fileCount', { n: 11 }), '11 файлов');
assert.equal(I18N.message('Wrong PIN'), 'Неверный PIN-код');
assert.equal(I18N.message('Locked out, try again in 42 s'), 'Слишком много попыток. Повторите через 42 с');
I18N.setLang('en');
assert.equal(I18N.t('v.fileCount', { n: 2 }), '2 files');
assert.equal(I18N.message('Wrong PIN'), 'Wrong PIN');
console.log(`Interface text: ${Object.keys(en).length} keys in English and Russian`);
