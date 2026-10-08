/**
 * Builds a portable Python runtime for packaging.
 * Windows: Python embeddable distribution + pip + engine deps (self-contained).
 * macOS/Linux: local venv fallback for developer builds.
 */
import { execSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const RUNTIME = path.join(ROOT, 'python-runtime');
const PY_VER = '3.10.11';
const isWin = process.platform === 'win32';

async function download(url, dest) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Download failed (${res.status}): ${url}`);
  fs.writeFileSync(dest, Buffer.from(await res.arrayBuffer()));
}

async function prepareWindows() {
  const zipPath = path.join(ROOT, '.python-embed.zip');
  const url = `https://www.python.org/ftp/python/${PY_VER}/python-${PY_VER}-embed-amd64.zip`;

  console.log('[prepare-runtime] Downloading Python embeddable...');
  await download(url, zipPath);

  if (fs.existsSync(RUNTIME)) fs.rmSync(RUNTIME, { recursive: true, force: true });
  fs.mkdirSync(RUNTIME, { recursive: true });

  execSync(
    `powershell -NoProfile -Command "Expand-Archive -Path '${zipPath.replace(/'/g, "''")}' -DestinationPath '${RUNTIME.replace(/'/g, "''")}' -Force"`,
    { stdio: 'inherit' },
  );

  const pthFile = fs.readdirSync(RUNTIME).find((f) => f.endsWith('._pth'));
  if (pthFile) {
    let content = fs.readFileSync(path.join(RUNTIME, pthFile), 'utf8');
    content = content.replace('#import site', 'import site');
    if (!content.includes('Lib\\site-packages')) content += '\nLib\\site-packages\n';
    fs.writeFileSync(path.join(RUNTIME, pthFile), content);
  }

  fs.mkdirSync(path.join(RUNTIME, 'Lib', 'site-packages'), { recursive: true });

  const getPip = path.join(ROOT, '.get-pip.py');
  console.log('[prepare-runtime] Installing pip...');
  await download('https://bootstrap.pypa.io/get-pip.py', getPip);

  const pythonExe = path.join(RUNTIME, 'python.exe');
  const pipEnv = { ...process.env, PYTHONNOUSERSITE: '1' };
  execSync(`"${pythonExe}" "${getPip}" --no-warn-script-location`, { stdio: 'inherit', env: pipEnv });

  const reqFile = path.join(ROOT, 'engine', 'requirements.txt');
  console.log('[prepare-runtime] Installing Python dependencies...');
  execSync(
    `"${pythonExe}" -m pip install -r "${reqFile}" --no-warn-script-location --no-user`,
    { stdio: 'inherit', env: pipEnv },
  );

  fs.unlinkSync(zipPath);
  fs.unlinkSync(getPip);
  console.log('[prepare-runtime] Portable runtime ready:', RUNTIME);
}

function prepareUnix() {
  if (fs.existsSync(RUNTIME)) fs.rmSync(RUNTIME, { recursive: true, force: true });
  execSync(`python3 -m venv "${RUNTIME}"`, { stdio: 'inherit', cwd: ROOT });
  const pip = path.join(RUNTIME, 'bin', 'pip');
  const reqFile = path.join(ROOT, 'engine', 'requirements.txt');
  execSync(`"${pip}" install -r "${reqFile}"`, { stdio: 'inherit' });
  console.log('[prepare-runtime] venv runtime ready:', RUNTIME);
}

try {
  if (isWin) await prepareWindows();
  else prepareUnix();
} catch (err) {
  console.error('[prepare-runtime] Failed:', err.message);
  process.exit(1);
}
