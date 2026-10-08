/**
 * Reads ANTHROPIC_API_KEY from .env / environment and writes an encrypted
 * bundle file for packaged builds. Never commit build-secrets/ to git.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { encryptBundledSecret } from '../lib/bundle-crypto.mjs';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const OUT_DIR = path.join(ROOT, 'build-secrets');
const OUT_FILE = path.join(OUT_DIR, 'anthropic.key.enc');

function loadDotEnv(filePath) {
  const vars = {};
  try {
    for (const line of fs.readFileSync(filePath, 'utf8').split('\n')) {
      const m = line.match(/^([A-Z_][A-Z0-9_]*)=(.*)$/);
      if (m) vars[m[1]] = m[2].replace(/^["']|["']$/g, '');
    }
  } catch {}
  return vars;
}

const dotEnv = loadDotEnv(path.join(ROOT, '.env'));
const apiKey = process.env.ANTHROPIC_API_KEY || dotEnv.ANTHROPIC_API_KEY;

fs.mkdirSync(OUT_DIR, { recursive: true });

if (apiKey?.trim()) {
  fs.writeFileSync(OUT_FILE, encryptBundledSecret(apiKey.trim()));
  console.log('[inject-secrets] Bundled default API key written for packaging.');
} else {
  try { fs.unlinkSync(OUT_FILE); } catch {}
  console.warn('[inject-secrets] ANTHROPIC_API_KEY not set — packaged app will rely on user-provided key or dev .env.');
}
