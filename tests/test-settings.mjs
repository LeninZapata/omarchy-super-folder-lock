// Settings.js + reglas de Core.js (puros).
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';

const dir = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const load = (f) => { const ctx = { module: { exports: {} } }; vm.runInNewContext(fs.readFileSync(path.join(dir, f), 'utf8').replace('.pragma library', ''), ctx); return ctx.module.exports; };
const S = load('Settings.js');
const C = load('Core.js');
const plain = (o) => JSON.parse(JSON.stringify(o));

// normalizar: defectos, rangos, claves desconocidas
assert.deepEqual(plain(S.normalize(null)), plain(S.defaults()));
let s = S.normalize({ showBarIcon: false, defaults: { idleLock: "off", idleSeconds: 30, workspaceLock: "maybe", x: 1 }, junk: 1 });
assert.equal(s.showBarIcon, false);
assert.equal(s.defaults.idleLock, "off");
assert.equal(s.defaults.idleSeconds, 600);       // 30 fuera de rango
assert.equal(s.defaults.workspaceLock, "on");    // valor desconocido → defecto
assert.equal(s.junk, undefined);

// regla efectiva: inherit → defecto; on/off propios mandan
const d = S.defaults();
let e = S.effective(d, { idleLock: "inherit", idleSeconds: null, workspaceLock: "off" });
assert.deepEqual(plain(e), { idleLock: true, workspaceLock: false, screenLock: true, openInFileManager: true, maxOpenLock: false, closeApps: false, idleSeconds: 600, maxOpenSeconds: 3600, closeAppsSeconds: 1800 });
e = S.effective(S.withDefault(d, "idleLock", "off"), { idleLock: "on", idleSeconds: 120 });
assert.equal(e.idleLock, true); assert.equal(e.idleSeconds, 120);
assert.equal(S.effective(S.withDefault(d, "idleLock", "off"), {}).idleLock, false);

// reglas de cierre
const eff = (r) => S.effective(d, r);
const open = {
  a: { workspaceId: 1, rules: {} },                                  // todo por defecto (on, 600 s)
  b: { workspaceId: 2, rules: { workspaceLock: "off", idleSeconds: 120 } },
  c: { workspaceId: 1, rules: { idleLock: "off", screenLock: "off" } },
};
assert.deepEqual(plain(C.lockOnWorkspace(open, eff, 1)), []);          // sigo en el 1; b no tiene la regla
assert.deepEqual(plain(C.lockOnWorkspace(open, eff, 5)), ['a', 'c']);
assert.deepEqual(plain(C.idleTargets(open, eff)), [120, 600]);
assert.deepEqual(plain(C.idleDue(open, eff, 119000)), []);
assert.deepEqual(plain(C.idleDue(open, eff, 120000)), ['b']);
assert.deepEqual(plain(C.idleDue(open, eff, 600000)), ['a', 'b']);
assert.deepEqual(plain(C.lockOnScreen(open, eff)), ['a', 'b']);
assert.deepEqual(plain(C.idleTargets({}, eff)), []);
// cuenta atrás: sin inactividad no hay; quietos desde hace 100 s con plazo 600 → 500
assert.equal(C.closeIn(open.a, eff, 1000000, 0), -1);
assert.equal(C.closeIn(open.a, eff, 1000000, 900000), 500);
assert.equal(C.closeIn(open.c, eff, 1000000, 900000), -1);   // c no tiene inactividad
// tiempo máximo abierta + posponer
const mo = { workspaceId: 1, openedAt: 0, rules: { maxOpenLock: "on", maxOpenSeconds: 300 } };
assert.deepEqual(plain(C.maxOpenDue({ m: mo }, eff, 299000)), []);
assert.deepEqual(plain(C.maxOpenDue({ m: mo }, eff, 300000)), ['m']);
assert.deepEqual(plain(C.maxOpenDue({ m: Object.assign({}, mo, { extraMs: 900000 }) }, eff, 300000)), []);
assert.equal(C.closeIn(mo, eff, 100000, 0), 200);
assert.equal(C.closeIn(mo, eff, 100000, 90000), 200);        // inactividad 600 s más lejana: manda el máximo
assert.equal(C.anyMaxOpen(open, eff), false);
assert.equal(C.anyMaxOpen({ m: mo }, eff), true);
assert.equal(S.effective(d, { maxOpenLock: "on", maxOpenSeconds: 100 }).maxOpenSeconds, 3600); // < 300 → defecto
// cerrar lo abierto: apagado por defecto, 30 min listos; la carpeta manda sobre el general
assert.equal(d.defaults.closeApps, "off"); assert.equal(d.defaults.closeAppsSeconds, 1800);
assert.deepEqual([S.effective(d, { closeApps: "on" }).closeApps, S.effective(d, { closeApps: "on" }).closeAppsSeconds], [true, 1800]);
assert.equal(S.effective(d, { closeApps: "on", closeAppsSeconds: 30 }).closeAppsSeconds, 1800);   // < 60 → defecto
assert.equal(S.effective(S.withDefault(d, "closeApps", "on"), { closeApps: "off" }).closeApps, false);
assert.equal(S.normalize({ defaults: { closeApps: "on", closeAppsSeconds: 600 } }).defaults.closeAppsSeconds, 600);
// puerta
assert.equal(C.gateExpired(0, 1e6, 120), false);
assert.equal(C.gateExpired(1e6, 1e6 + 119000, 120), false);
assert.equal(C.gateExpired(1e6, 1e6 + 120000, 120), true);
assert.equal(S.normalize({ gateTimeoutSeconds: 10 }).gateTimeoutSeconds, 120);
assert.equal(S.normalize({ gateTimeoutSeconds: 60 }).gateTimeoutSeconds, 60);
// ⚙ completo
let k = S.normalize({ showOpenDot: true, notifyAutoLock: "yes", hideOnShare: true, openShortcut: "SUPER + CTRL + K" });
assert.equal(k.showOpenDot, true); assert.equal(k.notifyAutoLock, false); assert.equal(k.hideOnShare, true);
assert.equal(k.openShortcut, "SUPER + CTRL + K");
assert.equal(S.normalize({ openShortcut: "SUPER + K; rm -rf" }).openShortcut, "");
assert.equal(S.withDefault(d, "notifyAutoLock", true).notifyAutoLock, true);
assert.equal(S.withDefault(d, "openShortcut", "SUPER + ALT + L").openShortcut, "SUPER + ALT + L");
console.log('settings ok');
