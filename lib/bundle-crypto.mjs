import crypto from 'node:crypto';

const DERIVED = crypto.scryptSync('lytesnap-ai-bundle-v1', 'lytesnap-salt', 32);

export function encryptBundledSecret(plaintext) {
  const iv = crypto.randomBytes(16);
  const cipher = crypto.createCipheriv('aes-256-gcm', DERIVED, iv);
  const enc = Buffer.concat([cipher.update(plaintext, 'utf8'), cipher.final()]);
  const tag = cipher.getAuthTag();
  return Buffer.concat([iv, tag, enc]);
}

export function decryptBundledSecret(buf) {
  const iv = buf.subarray(0, 16);
  const tag = buf.subarray(16, 32);
  const data = buf.subarray(32);
  const decipher = crypto.createDecipheriv('aes-256-gcm', DERIVED, iv);
  decipher.setAuthTag(tag);
  return Buffer.concat([decipher.update(data), decipher.final()]).toString('utf8');
}
