// Approval signatures, matching server/agent/core/policy.py exactly:
//   sig = hex(HMAC-SHA256(approval_key, `${action_id}|${payload_hash}|${nonce}|${decision}`))
// Pure functions only. Reading the key (biometric prompt) lives in secureKeys.ts.
import { hmac } from '@noble/hashes/hmac.js';
import { sha256 } from '@noble/hashes/sha2.js';
import { bytesToHex, utf8ToBytes } from '@noble/hashes/utils.js';

export type Decision = 'approve' | 'reject';

export interface SignedFields {
  actionId: string;
  payloadHash: string;
  nonce: string;
  decision: Decision;
}

export const APPROVAL_KEY_BYTES = 32;

const HEX64 = /^[0-9a-f]{64}$/;
const ACTION_ID = /^[0-9a-f]{32}$/;
const NONCE = /^[A-Za-z0-9_-]{1,128}$/;
const B64URL = /^[A-Za-z0-9_-]+$/;
const ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';

/** Decode the unpadded base64url approval key that /pair returns. Throws unless it is 32 bytes. */
export function decodeApprovalKey(encoded: string): Uint8Array {
  if (!B64URL.test(encoded) || encoded.length % 4 === 1) {
    throw new Error('invalid approval key');
  }
  const out = new Uint8Array(Math.floor((encoded.length * 6) / 8));
  let bits = 0;
  let value = 0;
  let index = 0;
  for (const ch of encoded) {
    value = (value << 6) | ALPHABET.indexOf(ch);
    bits += 6;
    if (bits >= 8) {
      bits -= 8;
      out[index++] = (value >> bits) & 0xff;
    }
  }
  if (out.length !== APPROVAL_KEY_BYTES) {
    out.fill(0);
    throw new Error('invalid approval key');
  }
  return out;
}

export function signatureMessage(fields: SignedFields): string {
  if (!ACTION_ID.test(fields.actionId)) throw new Error('invalid action id');
  if (!HEX64.test(fields.payloadHash)) throw new Error('invalid payload hash');
  if (!NONCE.test(fields.nonce)) throw new Error('invalid nonce');
  if (fields.decision !== 'approve' && fields.decision !== 'reject') {
    throw new Error('invalid decision');
  }
  return `${fields.actionId}|${fields.payloadHash}|${fields.nonce}|${fields.decision}`;
}

/** Lower-case hex HMAC-SHA256, the form policy.check_approval compares against. */
export function approvalSignature(key: Uint8Array, fields: SignedFields): string {
  if (key.length !== APPROVAL_KEY_BYTES) throw new Error('invalid approval key');
  return bytesToHex(hmac(sha256, key, utf8ToBytes(signatureMessage(fields))));
}
