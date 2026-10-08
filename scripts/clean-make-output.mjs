/**
 * Remove stale Squirrel output before rebuild.
 * Retries on Windows EBUSY when Explorer/antivirus holds old .nupkg files.
 */
import fs from 'node:fs';
import path from 'node:path';
import { execSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const MAKE_OUT = path.join(ROOT, 'out', 'make');

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

function tryKillAppProcesses() {
  if (process.platform !== 'win32') return;
  for (const name of ['lytesnap-ai.exe', 'LyteSnap.exe']) {
    try {
      execSync(`taskkill /F /IM ${name} /T`, { stdio: 'ignore' });
    } catch {}
  }
}

async function rmWithRetry(dir, attempts = 5) {
  for (let i = 1; i <= attempts; i++) {
    try {
      if (fs.existsSync(dir)) fs.rmSync(dir, { recursive: true, force: true });
      return true;
    } catch (err) {
      if (err.code !== 'EBUSY' && err.code !== 'EPERM') throw err;
      if (i === attempts) throw err;
      console.warn(`[clean-make] ${dir} locked (attempt ${i}/${attempts}) — retrying in 2s...`);
      await sleep(2000);
    }
  }
  return false;
}

tryKillAppProcesses();

if (fs.existsSync(MAKE_OUT)) {
  console.log('[clean-make] Removing', MAKE_OUT);
  await rmWithRetry(MAKE_OUT);
  console.log('[clean-make] Done.');
} else {
  console.log('[clean-make] Nothing to clean.');
}
