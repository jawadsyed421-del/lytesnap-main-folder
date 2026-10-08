/**
 * session-files.mjs — what the app knows about a stored YouTube session.
 *
 * The session may be stored two ways:
 *   session.enc   encrypted (engine/session_store.py)
 *   auth.json     plaintext (legacy)
 *
 * The app used to treat "auth.json exists" as "logged in". That is wrong twice
 * over: it misses an encrypted session entirely, and a revoked session leaves a
 * file that looks exactly like a live one. Only YouTube can confirm a session is
 * alive (engine/yt_auth.py does that with a browser); these helpers report what
 * is STORED, which is all the file system can honestly say.
 */

import fs from 'node:fs';
import path from 'node:path';

export const ENC_NAME = 'session.enc';
export const PLAIN_NAME = 'auth.json';
export const PROFILE_NAME = 'chrome_profile';

/** Everything the app writes that could identify or authenticate the user. */
export function sessionArtifacts(dataDir) {
  return [
    path.join(dataDir, ENC_NAME),
    path.join(dataDir, `${ENC_NAME}.bak`),
    path.join(dataDir, PLAIN_NAME),
    path.join(dataDir, `${PLAIN_NAME}.bak`),
    path.join(dataDir, 'auth.json.pre-encrypt.bak'),
    path.join(dataDir, PROFILE_NAME),
  ];
}

/**
 * What is stored, and how. `hasSession` means a session exists on disk — NOT
 * that it still works; call the Python live check for that.
 */
export function sessionStatus(dataDir) {
  const encPath = path.join(dataDir, ENC_NAME);
  const plainPath = path.join(dataDir, PLAIN_NAME);
  const encrypted = fs.existsSync(encPath);
  const plaintext = fs.existsSync(plainPath);

  let backend = null;
  let cookies = null;
  let written = null;
  if (encrypted) {
    try {
      const envelope = JSON.parse(fs.readFileSync(encPath, 'utf8'));
      backend = envelope.backend ?? null;
      cookies = envelope.cookies ?? null;
      written = envelope.written ?? null;
    } catch {
      // An unreadable envelope still means a session is stored; the Python
      // side reports why it cannot be opened.
    }
  }

  return {
    hasSession: encrypted || plaintext,
    // Kept for the existing renderer contract: it reads `loggedIn`.
    loggedIn: encrypted || plaintext,
    verified: false,
    storage: encrypted ? 'encrypted' : plaintext ? 'plaintext' : 'none',
    backend,
    cookies,
    written,
    plaintextPresent: plaintext,
    profilePresent: fs.existsSync(path.join(dataDir, PROFILE_NAME)),
  };
}

/**
 * Remove everything tied to the signed-in account.
 *
 * Deleting auth.json alone used to leave the Chrome profile behind — and that
 * profile caches the account's email address in its service-worker cache, so
 * "sign out" left the user's identity on disk. Returns what was removed.
 */
export function clearSession(dataDir) {
  const removed = [];
  const failed = [];
  for (const target of sessionArtifacts(dataDir)) {
    try {
      if (!fs.existsSync(target)) continue;
      fs.rmSync(target, { recursive: true, force: true });
      removed.push(path.basename(target));
    } catch (e) {
      failed.push({ file: path.basename(target), error: e.message });
    }
  }
  return { signedOut: failed.length === 0, removed, failed };
}
