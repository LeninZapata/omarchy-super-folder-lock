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

// Dueños de cada tecla, en TODOS los submaps (hl.unbind quita la tecla de todos).
const D = S.DESC;
const text = JSON.stringify([
  { modmask: 64, key: 'F', submap: '', description: 'Files' },
  { modmask: 68, key: 'K', submap: '', description: D },
  { modmask: 72, key: 'R', submap: '', description: D },
  { modmask: 72, key: 'R', submap: 'resize', description: 'Resize' },
  { modmask: 64, key: '', keycode: 10, submap: '', description: 'Workspace 1' },
]);
const own = S.owners(text);
assert.equal(own['SUPER + CTRL + K'].own, 1);
assert.equal(own['SUPER + ALT + R'].foreign, 1);
assert.equal(own['SUPER + 1'].foreign, 1);
assert.equal(S.owners(''), null);
assert.equal(S.owners('{}'), null);

let p = S.plan('SUPER + ALT + K', ['SUPER + CTRL + K'], own);
assert.ok(p.lua.includes('hl.unbind([[SUPER + CTRL + K]])') && p.lua.includes('hl.bind([[SUPER + ALT + K]]'), p.lua);
assert.equal(p.applied.join(), 'SUPER + ALT + K');
p = S.plan('SUPER + F', [], own);                        // ajeno: ni se pone ni se quita
assert.equal(p.conflict, 'SUPER + F'); assert.equal(p.lua, ''); assert.equal(p.applied.length, 0);
assert.equal(S.plan('SUPER + 1', [], own).conflict, 'SUPER + 1');
assert.equal(S.plan('', ['SUPER + ALT + R'], own).lua, '');   // comparte tecla en otro submap
assert.equal(S.plan('SUPER + ALT + R', [], own).conflict, 'SUPER + ALT + R');
p = S.plan('SUPER + ALT + K', ['SUPER + CTRL + K'], null);    // sin lista no se toca nada
assert.equal(p.lua, ''); assert.equal(p.retry, true); assert.equal(p.applied.join(), 'SUPER + CTRL + K');
assert.equal(S.plan('', [], own).lua, '');
console.log('shortcut ok');
