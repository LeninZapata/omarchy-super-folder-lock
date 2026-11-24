// Shortcut.js (puro).
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';

const src = fs.readFileSync(path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'Shortcut.js'), 'utf8').replace('.pragma library', '');
const ctx = { module: { exports: {} } };
vm.runInNewContext(src, ctx);
const S = ctx.module.exports;

assert.equal(S.norm('ctrl+super  + k'), 'SUPER + CTRL + K');
assert.equal(S.norm('K'), null);            // sin modificador
assert.equal(S.norm('SUPER + CTRL'), null); // sin tecla
assert.equal(S.norm('SUPER + K; rm'), null);
assert.equal(S.mask('SUPER + SHIFT + F'), 65);
const binds = [{ modmask: 64, key: 'F', submap: '', description: 'Files' }, { modmask: 68, key: 'K', submap: '', description: 'Super Folder Lock' }];
assert.equal(S.conflict(binds, 'SUPER + F'), true);
assert.equal(S.conflict(binds, 'SUPER + CTRL + K'), false);   // es nuestro
assert.equal(S.conflict(binds, 'SUPER + ALT + K'), false);
const lua = S.lua('SUPER + CTRL + K', 'SUPER + ALT + K');
assert.ok(lua.includes('hl.unbind([[SUPER + CTRL + K]])') && lua.includes('hl.bind([[SUPER + ALT + K]]'), lua);
assert.equal(S.lua(null, ''), '');
console.log('shortcut ok');
