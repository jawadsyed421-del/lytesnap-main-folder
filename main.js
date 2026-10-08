import { app, BrowserWindow, ipcMain, Notification, safeStorage } from 'electron';
import path from 'node:path';
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import started from 'electron-squirrel-startup';
import { decryptBundledSecret } from './lib/bundle-crypto.mjs';
import { sessionStatus, clearSession } from './lib/session-files.mjs';

if (started) app.quit();

// BUNDLE_DIR — read-only, contains code/scripts/venv (changes per build)
// DATA_DIR   — writable, contains user data (persists across updates)
const BUNDLE_DIR = app.isPackaged ? process.resourcesPath : app.getAppPath();
const DATA_DIR   = app.isPackaged ? app.getPath('userData') : app.getAppPath();

const ENGINE_DIR  = path.join(BUNDLE_DIR, 'engine');
const CONFIG_PATH = path.join(DATA_DIR,   'config.json');
const BEST_SCORE  = path.join(DATA_DIR,   'metrics', 'best_score.txt');
const LOGS_DIR    = path.join(DATA_DIR,   'running_logs');

// On first launch copy default config into userData so user can edit it
const DEFAULT_CONFIG = path.join(BUNDLE_DIR, 'config.json');
if (!fs.existsSync(CONFIG_PATH) && fs.existsSync(DEFAULT_CONFIG)) {
  fs.mkdirSync(path.dirname(CONFIG_PATH), { recursive: true });
  fs.copyFileSync(DEFAULT_CONFIG, CONFIG_PATH);
}

const USER_KEY_PATH = path.join(DATA_DIR, 'user-api-key.enc');
const BUNDLED_KEY_PATH = path.join(BUNDLE_DIR, 'build-secrets', 'anthropic.key.enc');

function readEnvFile(filePath) {
  const vars = {};
  try {
    for (const line of fs.readFileSync(filePath, 'utf8').split('\n')) {
      const m = line.match(/^([A-Z_][A-Z0-9_]*)=(.*)$/);
      if (m) vars[m[1]] = m[2].replace(/^["']|["']$/g, '');
    }
  } catch {}
  return vars;
}

function loadUserApiKey() {
  if (!fs.existsSync(USER_KEY_PATH)) return null;
  try {
    const encrypted = fs.readFileSync(USER_KEY_PATH);
    if (safeStorage.isEncryptionAvailable()) {
      return safeStorage.decryptString(encrypted);
    }
  } catch (e) {
    console.error('[lytesnap] failed to decrypt user API key:', e.message);
  }
  return null;
}

function loadBundledApiKey() {
  try {
    return decryptBundledSecret(fs.readFileSync(BUNDLED_KEY_PATH));
  } catch {}
  return null;
}

function resolveAnthropicApiKey() {
  const userKey = loadUserApiKey();
  if (userKey?.trim()) return userKey.trim();

  const bundledKey = loadBundledApiKey();
  if (bundledKey?.trim()) return bundledKey.trim();

  for (const p of [path.join(DATA_DIR, '.env'), path.join(BUNDLE_DIR, '.env')]) {
    const key = readEnvFile(p).ANTHROPIC_API_KEY;
    if (key?.trim()) return key.trim();
  }

  if (process.env.ANTHROPIC_API_KEY?.trim()) return process.env.ANTHROPIC_API_KEY.trim();
  return null;
}

function buildPythonEnv() {
  const env = { ...process.env, PYTHONNOUSERSITE: '1' };
  const apiKey = resolveAnthropicApiKey();
  if (apiKey) env.ANTHROPIC_API_KEY = apiKey;
  return env;
}

const PYTHON = (() => {
  const isWin = process.platform === 'win32';

  const candidates = isWin
    ? [
        path.join(BUNDLE_DIR, 'python-runtime', 'python.exe'),
        path.join(BUNDLE_DIR, '.venv', 'Scripts', 'python.exe'),
        path.join(BUNDLE_DIR, 'engine', '.venv', 'Scripts', 'python.exe'),
      ]
    : [
        path.join(BUNDLE_DIR, 'python-runtime', 'bin', 'python3'),
        path.join(BUNDLE_DIR, '.venv', 'bin', 'python3'),
        path.join(BUNDLE_DIR, 'engine', '.venv', 'bin', 'python3'),
      ];

  for (const p of candidates) {
    try {
      fs.accessSync(p, fs.constants.F_OK);
      return p;
    } catch {}
  }

  return isWin ? 'python' : 'python3';
})();

console.log('[lytesnap] BUNDLE_DIR:', BUNDLE_DIR);
console.log('[lytesnap] DATA_DIR:',   DATA_DIR);
console.log('[lytesnap] ENGINE_DIR:', ENGINE_DIR);
console.log('[lytesnap] PYTHON:', PYTHON);

let mainWindow;
let reshapeProcess = null;

const createWindow = () => {
  mainWindow = new BrowserWindow({
    width: 460,
    height: 820,
    resizable: false,
    titleBarStyle: 'hiddenInset',
    backgroundColor: '#1B1464',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  if (MAIN_WINDOW_VITE_DEV_SERVER_URL) {
    mainWindow.loadURL(MAIN_WINDOW_VITE_DEV_SERVER_URL);
  } else {
    mainWindow.loadFile(path.join(__dirname, `../renderer/${MAIN_WINDOW_VITE_NAME}/index.html`));
  }
};

app.whenReady().then(() => {
  createWindow();
  const status = getScheduleStatus();
  if (status.active) startScheduleLoop();
});

function killReshapeProcess() {
  if (reshapeProcess) {
    try { process.kill(-reshapeProcess.pid, 'SIGKILL'); } catch {}
    reshapeProcess = null;
  }
  if (authProcess) {
    try { process.kill(-authProcess.pid, 'SIGKILL'); } catch {}
    authProcess = null;
  }
}

app.on('window-all-closed', () => {
  killReshapeProcess();
  if (process.platform !== 'darwin') app.quit();
});

app.on('before-quit', killReshapeProcess);

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});

// ── IPC: read config ──────────────────────────────────────────────────────────
ipcMain.handle('get-config', () => {
  try { return JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8')); }
  catch { return {}; }
});

// ── IPC: write config ─────────────────────────────────────────────────────────
ipcMain.handle('set-config', (_, patch) => {
  const cfg = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'));
  Object.assign(cfg, patch);
  fs.writeFileSync(CONFIG_PATH, JSON.stringify(cfg, null, 2));
  return cfg;
});

// ── IPC: best score ───────────────────────────────────────────────────────────
ipcMain.handle('get-best-score', () => {
  try { return parseFloat(fs.readFileSync(BEST_SCORE, 'utf8').trim()); }
  catch { return 0; }
});

// ── IPC: experiment history ───────────────────────────────────────────────────
ipcMain.handle('get-history', () => {
  const logPath = path.join(DATA_DIR, 'metrics', 'experiment_log.csv');
  try {
    const lines = fs.readFileSync(logPath, 'utf8').trim().split('\n');
    return lines.slice(1).map(l => {
      const [timestamp, main_topic, narrow_topics, before_score, after_score, delta, kept, description] = l.split(',');
      return { timestamp, main_topic, narrow_topics,
        before_score: parseFloat(before_score),
        after_score: parseFloat(after_score),
        delta: parseFloat(delta), kept, description };
    }).reverse().slice(0, 20);
  } catch { return []; }
});

// ── IPC: score feed ───────────────────────────────────────────────────────────
ipcMain.handle('score-feed', async (_, topic) => {
  return new Promise((resolve) => {
    const proc = spawn(PYTHON, [
      path.join(ENGINE_DIR, 'score_feed_weighted.py'),
      '--topic', topic, '--output-json', '--data-dir', DATA_DIR,
    ], { cwd: BUNDLE_DIR, env: buildPythonEnv() });

    let out = '';
    proc.stdout.on('data', d => { out += d.toString(); });
    proc.stderr.on('data', d => { process.stderr.write(d); });
    proc.on('error', err => { console.error('[score error]', err.message); resolve({ weighted_score: 0, raw_score: 0, total: 0, matches: 0 }); });
    proc.on('close', () => {
      try {
        const result = JSON.parse(out.slice(out.indexOf('{')));
        if (result.positions?.length) {
          const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
          const metricsDir = path.join(DATA_DIR, 'metrics');
          fs.mkdirSync(metricsDir, { recursive: true });
          const logPath = path.join(metricsDir, `score_${ts}.txt`);
          const header = [
            `Score Log — ${ts}`,
            `Topics:  ${(result.topics || [topic]).join(' | ')}`,
            `Score:   ${(result.weighted_score * 100).toFixed(1)}% weighted  /  ${(result.raw_score * 100).toFixed(1)}% raw`,
            `Matches: ${result.matches} / ${result.total}`,
            '─'.repeat(60),
          ];
          const rows = result.positions.map(p =>
            `${p.match ? '✓' : '✗'}  #${String(p.rank).padStart(2)}  [w=${p.weight.toFixed(3)}]  ${p.title}`
          );
          const content = [...header, ...rows].join('\n') + '\n';
          fs.writeFileSync(logPath, content);
          process.stdout.write(`\n[score] ${logPath}\n${content}\n`);
        }
        resolve(result);
      } catch { resolve({ weighted_score: 0, raw_score: 0, total: 0, matches: 0 }); }
    });
  });
});

// ── Topic → config mapping ────────────────────────────────────────────────────
const TOPIC_MAP = {
  gaming:  { main: 'Gaming',  narrow: ['Minecraft gameplay', 'Fortnite highlights', 'GTA 5 gameplay', 'Call of Duty warzone'] },
  sports:  { main: 'Sports',  narrow: ['NFL football', 'NBA highlights', 'soccer skills', 'workout motivation'] },
  makeup:  { main: 'Makeup',  narrow: ['skincare routine', 'makeup tutorial', 'natural beauty', 'beauty product review'] },
  drama:   { main: 'Drama',   narrow: ['Netflix series recommendations', 'TV show review', 'romance drama series', 'thriller TV show'] },
  finance:    { main: 'Finance',    narrow: ['stock market investing', 'personal finance tips', 'index funds', 'real estate investing'] },
  democrat:   { main: 'pro-Democrat progressive commentary',   narrow: ['progressive politics commentary', 'liberal news analysis', 'Democratic Party supporters', 'left-wing political commentary'] },
  republican: { main: 'Republican', narrow: ['Republican Party news', 'conservative politics', 'Trump rally', 'MAGA news'] },
};

// ── Schedule ──────────────────────────────────────────────────────────────────
const SCHEDULE_STATE_PATH = path.join(DATA_DIR, 'schedules', 'schedule_state.json');
const INTENSIVE_INTERVAL_MS = 3 * 60 * 60 * 1000; // 3 hours

let scheduleCheckTimer = null;

function getScheduleStatus() {
  try {
    const state = JSON.parse(fs.readFileSync(SCHEDULE_STATE_PATH, 'utf8'));
    const start = new Date(state.startDate);
    const todayMidnight = new Date(); todayMidnight.setHours(0, 0, 0, 0);
    const startMidnight = new Date(start); startMidnight.setHours(0, 0, 0, 0);
    const daysElapsed = Math.floor((todayMidnight - startMidnight) / 86400000);
    if (daysElapsed >= 7) return { active: false, phase: 'complete', daysElapsed, startDate: state.startDate };
    const phase = daysElapsed < 3 ? 'intensive' : 'maintenance';
    return { active: true, phase, daysElapsed, startDate: state.startDate, lastRunTime: state.lastRunTime || null, nextRunTime: state.nextRunTime || null };
  } catch {
    return { active: false, phase: 'inactive' };
  }
}

function activateSchedule() {
  const now = new Date();
  const today = now.toISOString().slice(0, 10);
  const jitterMs = (60 + Math.random() * 240) * 1000;
  const nextRunTime = new Date(now.getTime() + INTENSIVE_INTERVAL_MS + jitterMs).toISOString();
  fs.mkdirSync(path.join(DATA_DIR, 'schedules'), { recursive: true });
  fs.writeFileSync(SCHEDULE_STATE_PATH, JSON.stringify({
    startDate: today,
    lastRunDate: today,
    lastRunTime: now.toISOString(),
    nextRunTime,
  }, null, 2));
  startScheduleLoop();
  console.log('[lytesnap] 7-day treatment schedule activated:', today);
  mainWindow?.webContents.send('schedule-status-changed', getScheduleStatus());
}

function runScheduledSession() {
  if (reshapeProcess) { console.log('[schedule] session already running — skipping'); return; }

  const now = new Date();
  const today = now.toISOString().slice(0, 10);

  // Update state before spawning so concurrent checks can't double-fire
  try {
    const state = JSON.parse(fs.readFileSync(SCHEDULE_STATE_PATH, 'utf8'));
    state.lastRunDate = today;
    state.lastRunTime = now.toISOString();
    const jitterMs = (60 + Math.random() * 240) * 1000;
    const nextRunTime = new Date(now.getTime() + INTENSIVE_INTERVAL_MS + jitterMs).toISOString();
    state.nextRunTime = nextRunTime;
    fs.writeFileSync(SCHEDULE_STATE_PATH, JSON.stringify(state, null, 2));
  } catch (e) { console.error('[schedule] state update failed:', e.message); return; }

  const ts = now.toISOString().replace(/[:.]/g, '-').slice(0, 19);
  const runDir = path.join(LOGS_DIR, ts);
  fs.mkdirSync(runDir, { recursive: true });

  console.log(`[schedule] starting session — ${ts}`);
  mainWindow?.webContents.send('scheduled-session-started', { startTime: now.toISOString(), phase: 'unaddict' });

  reshapeProcess = spawn(PYTHON, [path.join(ENGINE_DIR, 'youtube_reshaper.py'), '--run-dir', runDir, '--data-dir', DATA_DIR], { cwd: BUNDLE_DIR, detached: true, env: buildPythonEnv() });
  const logStream = fs.createWriteStream(path.join(runDir, 'session.log'), { flags: 'w' });
  reshapeProcess.stdout.pipe(logStream);
  reshapeProcess.stderr.pipe(logStream);
  reshapeProcess.stdout.on('data', d => { process.stdout.write(d); mainWindow?.webContents.send('session-log', d.toString()); });
  reshapeProcess.stderr.on('data', d => { process.stderr.write(d); mainWindow?.webContents.send('session-log', d.toString()); });
  reshapeProcess.on('close', code => {
    reshapeProcess = null;
    console.log(`[schedule] session complete (code ${code})`);
    new Notification({ title: 'LyteSnap', body: 'Scheduled session complete.' }).show();
    mainWindow?.webContents.send('session-complete', { code, scheduled: true });
    mainWindow?.webContents.send('schedule-status-changed', getScheduleStatus());
  });
  reshapeProcess.on('error', err => { reshapeProcess = null; console.error('[schedule] spawn error:', err.message); });
}

function scheduleCheck() {
  const status = getScheduleStatus();
  if (!status.active) { stopScheduleLoop(); return; }

  const now = Date.now();
  const lastRun = status.lastRunTime ? new Date(status.lastRunTime).getTime() : 0;
  const today = new Date().toISOString().slice(0, 10);

  if (status.phase === 'intensive') {
    const state = JSON.parse(fs.readFileSync(SCHEDULE_STATE_PATH, 'utf8'));
    const nextRun = state.nextRunTime ? new Date(state.nextRunTime).getTime() : lastRun + INTENSIVE_INTERVAL_MS;
    if (now >= nextRun) runScheduledSession();
  } else if (status.phase === 'maintenance') {
    const state = JSON.parse(fs.readFileSync(SCHEDULE_STATE_PATH, 'utf8'));
    if (state.lastRunDate !== today) runScheduledSession();
  }
}

function startScheduleLoop() {
  if (scheduleCheckTimer) return;
  scheduleCheckTimer = setInterval(scheduleCheck, 60 * 60 * 1000); // check every hour
  console.log('[schedule] loop started');
}

function stopScheduleLoop() {
  if (scheduleCheckTimer) { clearInterval(scheduleCheckTimer); scheduleCheckTimer = null; }
}

// ── IPC: start session ────────────────────────────────────────────────────────
ipcMain.handle('start-session', async (_, { topics, phase }) => {
  if (reshapeProcess) return { error: 'Session already running' };

  const mappings = [...new Set(topics)].filter(t => TOPIC_MAP[t]).map(t => TOPIC_MAP[t]);
  if (!mappings.length) return { error: 'No valid topics selected' };
  const main_topic = mappings.map(m => m.main).join(' or ');
  const narrow_topics = mappings.flatMap(m => m.narrow);
  console.log('[lytesnap] start-session:', main_topic, '| phase:', phase, '| python:', PYTHON);

  try {
    const cfg = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'));
    cfg.main_topic = main_topic;
    cfg.narrow_topics = narrow_topics;
    fs.writeFileSync(CONFIG_PATH, JSON.stringify(cfg, null, 2));
  } catch (e) {
    console.error('[lytesnap] config write failed:', e.message);
    return { error: `Config write failed: ${e.message}` };
  }

  // Auto-activate 7-day treatment schedule on first unaddict session
  if (phase === 'unaddict') {
    const status = getScheduleStatus();
    if (!status.active && status.phase !== 'complete') activateSchedule();
  }

  const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
  const runDir = path.join(LOGS_DIR, ts);
  fs.mkdirSync(runDir, { recursive: true });

  return new Promise((resolve) => {
    reshapeProcess = spawn(PYTHON, [path.join(ENGINE_DIR, 'youtube_reshaper.py'), '--run-dir', runDir, '--data-dir', DATA_DIR], { cwd: BUNDLE_DIR, detached: true, env: buildPythonEnv() });
    const logStream = fs.createWriteStream(path.join(runDir, 'session.log'), { flags: 'w' });
    reshapeProcess.stdout.pipe(logStream);
    reshapeProcess.stderr.pipe(logStream);

    reshapeProcess.stdout.on('data', d => { process.stdout.write(d); mainWindow?.webContents.send('session-log', d.toString()); });
    reshapeProcess.stderr.on('data', d => { process.stderr.write(d); mainWindow?.webContents.send('session-log', d.toString()); });

    reshapeProcess.on('error', err => {
      console.error('[lytesnap] spawn error:', err.message);
      reshapeProcess = null;
      mainWindow?.webContents.send('session-complete', { code: 1, error: err.message });
      resolve({ error: err.message });
    });

    reshapeProcess.on('close', code => {
      reshapeProcess = null;
      mainWindow?.webContents.send('session-complete', { code });
      new Notification({
        title: 'LyteSnap session complete',
        body: `Feed reshaped toward ${main_topic}.`,
      }).show();
    });

    resolve({ started: true, topic: main_topic });
  });
});

// ── IPC: stop session ─────────────────────────────────────────────────────────
ipcMain.handle('stop-session', () => {
  if (reshapeProcess) { reshapeProcess.kill('SIGTERM'); reshapeProcess = null; }
  return { stopped: true };
});

// ── IPC: session status ───────────────────────────────────────────────────────
ipcMain.handle('session-status', () => ({ running: reshapeProcess !== null }));

// ── IPC: API key (user override; default key never exposed) ───────────────────
ipcMain.handle('get-api-key-status', () => ({
  hasCustomKey: fs.existsSync(USER_KEY_PATH),
}));

ipcMain.handle('set-user-api-key', (_, { key }) => {
  const trimmed = (key || '').trim();
  if (!trimmed) return { error: 'API key cannot be empty' };
  if (!safeStorage.isEncryptionAvailable()) {
    return { error: 'Secure storage is unavailable on this system' };
  }
  try {
    fs.writeFileSync(USER_KEY_PATH, safeStorage.encryptString(trimmed));
    return { saved: true };
  } catch (e) {
    return { error: e.message };
  }
});

ipcMain.handle('clear-user-api-key', () => {
  try { fs.unlinkSync(USER_KEY_PATH); } catch {}
  return { cleared: true };
});

// ── IPC: auth status ──────────────────────────────────────────────────────────
// Reports what is STORED (encrypted or plaintext). It cannot tell whether the
// session still works — only YouTube can, via engine/yt_auth.py.
ipcMain.handle('auth-status', () => sessionStatus(DATA_DIR));

// ── IPC: sign out (remove every trace of the account) ────────────────────────
// Deletes the encrypted session, the legacy plaintext, their backups AND the
// Chrome profile, which caches the account's email address.
ipcMain.handle('sign-out', () => clearSession(DATA_DIR));

// ── IPC: start auth setup (opens Chrome for login) ───────────────────────────
let authProcess = null;
ipcMain.handle('start-auth', async () => {
  if (authProcess) return { error: 'Auth already in progress' };
  return new Promise((resolve) => {
    let authLog = '';
    authProcess = spawn(PYTHON, [path.join(ENGINE_DIR, 'setup_auth.py'), '--data-dir', DATA_DIR], { cwd: BUNDLE_DIR, env: buildPythonEnv() });
    authProcess.stdout.on('data', d => {
      authLog += d.toString();
      process.stdout.write(d);
      mainWindow?.webContents.send('auth-log', d.toString());
    });
    authProcess.stderr.on('data', d => {
      authLog += d.toString();
      process.stderr.write(d);
      mainWindow?.webContents.send('auth-log', d.toString());
    });
    authProcess.on('error', err => {
      authProcess = null;
      const error = err.message.includes('ENOENT')
        ? 'Could not start Python runtime. Please reinstall the app.'
        : err.message;
      mainWindow?.webContents.send('auth-complete', { success: false, error });
      resolve({ error });
    });
    authProcess.on('close', code => {
      const success = code === 0 && sessionStatus(DATA_DIR).hasSession;
      let error = null;
      if (!success) {
        if (code === 2 || /Google Chrome is required/i.test(authLog)) {
          error = 'Google Chrome is required for YouTube sign-in. Please install Chrome and try again.';
        } else if (/Timed out waiting for login/i.test(authLog)) {
          error = 'Login timed out. Complete sign-in within 5 minutes and try again.';
        } else {
          error = 'Login failed. Please try again.';
        }
      }
      authProcess = null;
      mainWindow?.webContents.send('auth-complete', { success, error });
    });
    resolve({ started: true });
  });
});

// ── IPC: schedule control (manual toggle) ────────────────────────────────────
ipcMain.handle('set-schedule', (_, { enabled }) => {
  if (!enabled) {
    stopScheduleLoop();
    try { fs.unlinkSync(SCHEDULE_STATE_PATH); } catch {}
    return { scheduled: false };
  }
  activateSchedule();
  return { scheduled: true, intervalHours: 3 };
});

// ── IPC: schedule status ──────────────────────────────────────────────────────
ipcMain.handle('get-schedule-status', () => getScheduleStatus());

// ── IPC: reset schedule to day 1 ─────────────────────────────────────────────
ipcMain.handle('reset-schedule', () => {
  const today = new Date().toISOString().slice(0, 10);
  fs.mkdirSync(path.join(DATA_DIR, 'schedules'), { recursive: true });
  fs.writeFileSync(SCHEDULE_STATE_PATH, JSON.stringify({
    startDate: today,
    lastRunDate: null,
    lastRunTime: null,
    nextRunTime: null,
  }, null, 2));
  mainWindow?.webContents.send('schedule-status-changed', getScheduleStatus());
  return getScheduleStatus();
});
