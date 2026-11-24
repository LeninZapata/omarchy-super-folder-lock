// Lógica pura de Core.js (sin QML).
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';

const src = fs.readFileSync(path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'Core.js'), 'utf8')
  .replace('.pragma library', '');
const ctx = { module: { exports: {} } };
vm.runInNewContext(src, ctx);
const Core = ctx.module.exports;

// faillock: 2 fallos → quedan 8; 10 fallos recientes → espera
const line = (t) => `${t}  RHOST           TTY   V`;
const now = new Date(2026, 10, 23, 18, 0, 0).getTime();
let info = Core.faillockInfo(['When                Type  Source                                           Valid',
  '2026-11-23 17:59:00 RHOST  -  V', '2026-11-23 17:59:30 RHOST  -  V'].join('\n'), now, 10, 120);
assert.equal(info.failures, 2); assert.equal(info.left, 8); assert.equal(info.wait, 0);
const ten = Array.from({ length: 10 }, (_, i) => `2026-11-23 17:59:${String(i * 5).padStart(2, '0')} RHOST  -  V`).join('\n');
info = Core.faillockInfo(ten, now, 10, 120);
assert.equal(info.left, 0); assert.ok(info.wait > 0 && info.wait <= 120, String(info.wait));
assert.equal(Core.faillockInfo('', now, 10, 120).left, 10);
console.log('core ok');
