"""
session_store.py - encrypted storage for a saved YouTube session
================================================================

A YouTube session (Playwright `storage_state`: ~60 cookies) is a bearer
credential. Anyone holding the file can open the account without a password or
2FA, so it should not sit on disk in clear text. This module stores it
encrypted and hands the decrypted state back as a dict, so the plaintext never
has to touch disk at all.

Backends
--------
dpapi    Windows DPAPI (CryptProtectData). The key is the OS user account; no
         key material to manage. Same mechanism the Electron app already uses
         for the Anthropic key. Cannot be decrypted by another user, another
         machine, or a re-imaged VM - which is exactly why it does not suit a
         fleet.
aesgcm   AES-256-GCM with a key supplied from outside, base64 in
         LYTESNAP_SESSION_KEY. Works anywhere, and is the hook a KMS or secret
         manager plugs into later: the fleet fetches the data key, exports it
         into the pod, and this backend uses it.
none     Plain JSON. What the project did before. Explicit, not accidental.

File layout in a data dir
-------------------------
    session.enc   encrypted envelope (this module)
    auth.json     plaintext storage_state (legacy; still read if present)

Enabling encryption breaks the readers that still open auth.json directly -
`score_feed.py` and the Electron app's auth-status check. `migrate()` leaves
the plaintext in place unless asked to drop it, so the switch can be staged.

Usage
-----
    state = session_store.load(data_dir)             # dict or None
    session_store.save(state, data_dir, "dpapi")     # encrypt + write
    session_store.migrate(data_dir, "dpapi", keep_plaintext=False)
    session_store.status(data_dir)                   # what is stored, how
"""

import base64
import json
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

ENVELOPE_VERSION = 1
ENC_NAME = "session.enc"
PLAIN_NAME = "auth.json"

# Domain separation: ciphertext made here cannot be fed to another DPAPI
# consumer on the same account, and vice versa.
DPAPI_ENTROPY = b"lytesnap.session.v1"
AESGCM_KEY_ENV = "LYTESNAP_SESSION_KEY"
BACKEND_ENV = "LYTESNAP_SESSION_BACKEND"

BACKENDS = ("dpapi", "aesgcm", "none")


class SessionStoreError(Exception):
    """Storing or retrieving the session failed. The message says which."""


# ---------------------------------------------------------------------------
# Backend: Windows DPAPI
# ---------------------------------------------------------------------------

def dpapi_available() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        return bool(ctypes.windll.crypt32)
    except Exception:
        return False


def _dpapi_blobs():
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_char))]

    return ctypes, DATA_BLOB


def _dpapi_call(func, data: bytes) -> bytes:
    """Run CryptProtectData / CryptUnprotectData over `data`."""
    ctypes, DATA_BLOB = _dpapi_blobs()

    # The buffers must stay referenced for the duration of the call.
    buf_in = ctypes.create_string_buffer(data, len(data))
    blob_in = DATA_BLOB(len(data), ctypes.cast(buf_in, ctypes.POINTER(ctypes.c_char)))

    buf_ent = ctypes.create_string_buffer(DPAPI_ENTROPY, len(DPAPI_ENTROPY))
    blob_ent = DATA_BLOB(len(DPAPI_ENTROPY),
                         ctypes.cast(buf_ent, ctypes.POINTER(ctypes.c_char)))

    blob_out = DATA_BLOB()
    CRYPTPROTECT_UI_FORBIDDEN = 0x01

    ok = func(
        ctypes.byref(blob_in),
        None,
        ctypes.byref(blob_ent),
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(blob_out),
    )
    if not ok:
        # DPAPI returns ERROR_INVALID_DATA for both causes, so name both.
        raise SessionStoreError(
            "DPAPI could not decrypt the session (error %d): either the file "
            "was altered, or it was encrypted by a different Windows user or "
            "on a different machine." % ctypes.GetLastError()
        )
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def _dpapi_encrypt(plaintext: bytes) -> dict:
    import ctypes
    blob = _dpapi_call(ctypes.windll.crypt32.CryptProtectData, plaintext)
    return {"ciphertext": base64.b64encode(blob).decode("ascii")}


def _dpapi_decrypt(envelope: dict) -> bytes:
    import ctypes
    blob = base64.b64decode(envelope["ciphertext"])
    return _dpapi_call(ctypes.windll.crypt32.CryptUnprotectData, blob)


# ---------------------------------------------------------------------------
# Backend: AES-256-GCM with an externally supplied key
# ---------------------------------------------------------------------------

def generate_key() -> str:
    """A fresh base64 key for LYTESNAP_SESSION_KEY."""
    return base64.b64encode(os.urandom(32)).decode("ascii")


def _aesgcm_key() -> bytes:
    raw = os.environ.get(AESGCM_KEY_ENV, "")
    if not raw:
        raise SessionStoreError(
            "%s is not set. Generate one with:  python engine/session_store.py "
            "--generate-key" % AESGCM_KEY_ENV
        )
    try:
        key = base64.b64decode(raw)
    except Exception:
        raise SessionStoreError("%s is not valid base64" % AESGCM_KEY_ENV)
    if len(key) != 32:
        raise SessionStoreError(
            "%s must decode to 32 bytes, got %d" % (AESGCM_KEY_ENV, len(key))
        )
    return key


def _aesgcm():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        return AESGCM
    except ImportError:
        raise SessionStoreError(
            "the aesgcm backend needs the 'cryptography' package: "
            "pip install cryptography"
        )


def _aesgcm_encrypt(plaintext: bytes) -> dict:
    AESGCM = _aesgcm()
    nonce = os.urandom(12)
    ct = AESGCM(_aesgcm_key()).encrypt(nonce, plaintext, DPAPI_ENTROPY)
    return {
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ciphertext": base64.b64encode(ct).decode("ascii"),
    }


def _aesgcm_decrypt(envelope: dict) -> bytes:
    AESGCM = _aesgcm()
    try:
        nonce = base64.b64decode(envelope["nonce"])
        ct = base64.b64decode(envelope["ciphertext"])
        return AESGCM(_aesgcm_key()).decrypt(nonce, ct, DPAPI_ENTROPY)
    except SessionStoreError:
        raise
    except Exception:
        # GCM fails closed: wrong key and tampered bytes are indistinguishable.
        raise SessionStoreError(
            "could not decrypt the session: wrong key, or the file was altered"
        )


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------

def default_backend() -> str:
    """What to encrypt with when the caller did not say."""
    env = os.environ.get(BACKEND_ENV, "").strip().lower()
    if env:
        if env not in BACKENDS:
            raise SessionStoreError(
                "%s=%s is not one of %s" % (BACKEND_ENV, env, ", ".join(BACKENDS))
            )
        return env
    if os.environ.get(AESGCM_KEY_ENV):
        return "aesgcm"          # a key was supplied: the fleet path
    if dpapi_available():
        return "dpapi"
    return "none"


def _encrypt(plaintext: bytes, backend: str) -> dict:
    if backend == "dpapi":
        if not dpapi_available():
            raise SessionStoreError("the dpapi backend is Windows-only")
        return _dpapi_encrypt(plaintext)
    if backend == "aesgcm":
        return _aesgcm_encrypt(plaintext)
    raise SessionStoreError("unknown backend '%s'" % backend)


def _decrypt(envelope: dict) -> bytes:
    backend = envelope.get("backend")
    if backend == "dpapi":
        if not dpapi_available():
            raise SessionStoreError(
                "this session was encrypted with DPAPI and can only be read on "
                "the Windows account that wrote it"
            )
        return _dpapi_decrypt(envelope)
    if backend == "aesgcm":
        return _aesgcm_decrypt(envelope)
    raise SessionStoreError("unknown backend '%s' in the stored session" % backend)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def enc_path(data_dir) -> Path:
    return Path(data_dir) / ENC_NAME


def plain_path(data_dir) -> Path:
    return Path(data_dir) / PLAIN_NAME


# ---------------------------------------------------------------------------
# Read / write
# ---------------------------------------------------------------------------

def load(data_dir, prefer_encrypted: bool = True):
    """Return the session state dict, or None if there is none.

    Reads session.enc when present, else the legacy plaintext auth.json.
    """
    enc = enc_path(data_dir)
    plain = plain_path(data_dir)

    if prefer_encrypted and enc.exists():
        try:
            envelope = json.loads(enc.read_text(encoding="utf-8"))
        except Exception as e:
            raise SessionStoreError("%s is not readable: %s" % (ENC_NAME, e))
        if envelope.get("lytesnap_session") != ENVELOPE_VERSION:
            raise SessionStoreError(
                "%s has version %r, this build writes %d"
                % (ENC_NAME, envelope.get("lytesnap_session"), ENVELOPE_VERSION)
            )
        return json.loads(_decrypt(envelope).decode("utf-8"))

    if plain.exists():
        try:
            return json.loads(plain.read_text(encoding="utf-8"))
        except Exception as e:
            raise SessionStoreError("%s is not readable JSON: %s" % (PLAIN_NAME, e))

    return None


def save(state: dict, data_dir, backend: str = None) -> Path:
    """Encrypt and write the session. Returns the path written.

    backend "none" writes plaintext auth.json, which is what the project did
    before; anything else writes session.enc.
    """
    backend = backend or default_backend()
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state, indent=2).encode("utf-8")

    if backend == "none":
        target = plain_path(data_dir)
        tmp = target.with_suffix(".json.tmp")
        if target.exists():
            shutil.copy2(target, target.with_suffix(".json.bak"))
        tmp.write_bytes(payload)
        os.replace(tmp, target)
        return target

    envelope = {
        "lytesnap_session": ENVELOPE_VERSION,
        "backend": backend,
        "written": datetime.now().isoformat(timespec="seconds"),
        "cookies": len(state.get("cookies") or []),   # metadata, not secret
    }
    envelope.update(_encrypt(payload, backend))

    target = enc_path(data_dir)
    tmp = target.with_suffix(".enc.tmp")
    if target.exists():
        shutil.copy2(target, target.with_suffix(".enc.bak"))
    tmp.write_text(json.dumps(envelope, indent=2), encoding="utf-8")
    os.replace(tmp, target)
    _restrict(target)
    return target


def _restrict(path: Path) -> None:
    """Best-effort owner-only permissions. Encryption is the real control."""
    try:
        if sys.platform != "win32":
            os.chmod(path, 0o600)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

def migrate(data_dir, backend: str = None, keep_plaintext: bool = False) -> dict:
    """Encrypt an existing plaintext auth.json into session.enc.

    Verifies the ciphertext decrypts back to the original before removing any
    plaintext - a migration that loses the session is worse than no migration.
    """
    backend = backend or default_backend()
    if backend == "none":
        raise SessionStoreError("backend 'none' would not encrypt anything")

    plain = plain_path(data_dir)
    if not plain.exists():
        raise SessionStoreError("no %s to migrate in %s" % (PLAIN_NAME, data_dir))

    original = json.loads(plain.read_text(encoding="utf-8"))
    target = save(original, data_dir, backend)

    roundtrip = load(data_dir)
    if roundtrip != original:
        raise SessionStoreError(
            "verification failed: the encrypted copy did not read back "
            "identically; plaintext left untouched"
        )

    removed = False
    if not keep_plaintext:
        backup = plain.with_suffix(".json.pre-encrypt.bak")
        shutil.copy2(plain, backup)
        plain.unlink()
        removed = True

    return {
        "backend": backend,
        "written": str(target),
        "cookies": len(original.get("cookies") or []),
        "plaintext_removed": removed,
    }


def decrypt_to_plaintext(data_dir) -> Path:
    """Write the session back out as plaintext auth.json. Reverses migrate()."""
    state = load(data_dir)
    if state is None:
        raise SessionStoreError("no session to decrypt in %s" % data_dir)
    return save(state, data_dir, "none")


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def status(data_dir) -> dict:
    enc = enc_path(data_dir)
    plain = plain_path(data_dir)
    out = {
        "data_dir": str(data_dir),
        "encrypted": enc.exists(),
        "plaintext": plain.exists(),
        "backend": None,
        "written": None,
        "cookies": None,
        "default_backend": None,
        "warnings": [],
    }
    try:
        out["default_backend"] = default_backend()
    except SessionStoreError as e:
        out["warnings"].append(str(e))

    if enc.exists():
        try:
            envelope = json.loads(enc.read_text(encoding="utf-8"))
            out["backend"] = envelope.get("backend")
            out["written"] = envelope.get("written")
            out["cookies"] = envelope.get("cookies")
        except Exception as e:
            out["warnings"].append("%s unreadable: %s" % (ENC_NAME, e))

    if out["encrypted"] and out["plaintext"]:
        out["warnings"].append(
            "both session.enc and auth.json exist - the plaintext copy still "
            "grants account access; remove it once the legacy readers are updated"
        )
    if not out["encrypted"] and out["plaintext"]:
        out["warnings"].append(
            "session is stored in clear text; encrypt with: "
            "measure_feed.py auth --encrypt"
        )
    return out


def format_status(st: dict) -> str:
    lines = ["  data dir:   " + st["data_dir"]]
    if st["encrypted"]:
        lines.append("  storage:    encrypted (%s), %s cookies, written %s"
                     % (st["backend"], st["cookies"], st["written"]))
    elif st["plaintext"]:
        lines.append("  storage:    PLAINTEXT auth.json")
    else:
        lines.append("  storage:    none")
    lines.append("  default backend here: %s" % st["default_backend"])
    for w in st["warnings"]:
        lines.append("  ! " + w)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse

    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    ap = argparse.ArgumentParser(description="Encrypted YouTube session storage")
    ap.add_argument("--data-dir", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--encrypt", action="store_true", help="auth.json -> session.enc")
    ap.add_argument("--decrypt", action="store_true", help="session.enc -> auth.json")
    ap.add_argument("--keep-plaintext", action="store_true",
                    help="with --encrypt, leave auth.json in place")
    ap.add_argument("--backend", choices=BACKENDS, default=None)
    ap.add_argument("--generate-key", action="store_true",
                    help="print a fresh base64 key for " + AESGCM_KEY_ENV)
    args = ap.parse_args()

    if args.generate_key:
        print(generate_key())
        return

    try:
        if args.encrypt:
            result = migrate(args.data_dir, args.backend, args.keep_plaintext)
            print("  encrypted %d cookies with %s -> %s"
                  % (result["cookies"], result["backend"], result["written"]))
            print("  plaintext removed: %s" % result["plaintext_removed"])
            if not result["plaintext_removed"]:
                print("  ! auth.json still grants account access")
            return
        if args.decrypt:
            path = decrypt_to_plaintext(args.data_dir)
            print("  wrote plaintext %s" % path)
            print("  ! this file grants account access to anyone who reads it")
            return
    except SessionStoreError as e:
        print("  error: %s" % e)
        sys.exit(1)

    print()
    print(format_status(status(args.data_dir)))
    print()


if __name__ == "__main__":
    main()
