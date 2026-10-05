import fs from 'fs';
import path from 'path';

import {
  approvalSignature,
  decodeApprovalKey,
  signatureMessage,
  type SignedFields,
} from '../approvalSignature';

interface Vector {
  action_id: string;
  payload_hash: string;
  nonce: string;
  decision: 'approve' | 'reject';
  message: string;
  sig: string;
}

const vectors = JSON.parse(
  fs.readFileSync(
    path.join(__dirname, '../../../../shared/test-vectors/approval-signature.json'),
    'utf8',
  ),
) as { approval_key_b64url: string; cases: Vector[] };

const fieldsOf = (v: Vector): SignedFields => ({
  actionId: v.action_id,
  payloadHash: v.payload_hash,
  nonce: v.nonce,
  decision: v.decision,
});

const base = fieldsOf(vectors.cases[0]);

describe('approval signature vectors', () => {
  const key = decodeApprovalKey(vectors.approval_key_b64url);

  it.each(vectors.cases.map((v, i) => [i, v] as const))(
    'case %i matches message and signature',
    (_i, v) => {
      expect(signatureMessage(fieldsOf(v))).toBe(v.message);
      expect(approvalSignature(key, fieldsOf(v))).toBe(v.sig);
    },
  );
});

describe('decodeApprovalKey', () => {
  it('decodes 32 bytes', () => {
    expect(decodeApprovalKey(vectors.approval_key_b64url)).toHaveLength(32);
  });

  it.each([
    ['too short', 'AAECAwQF'],
    ['too long', vectors.approval_key_b64url + 'AAAA'],
    ['bad characters', 'AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh+='],
    ['standard base64 symbols', 'AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh/+'],
    ['empty', ''],
  ])('rejects %s', (_name, encoded) => {
    expect(() => decodeApprovalKey(encoded)).toThrow('invalid approval key');
  });
});

describe('signatureMessage and approvalSignature validation', () => {
  it('rejects a bad action id', () => {
    expect(() => signatureMessage({ ...base, actionId: 'nope' })).toThrow('invalid action id');
  });

  it('rejects a bad payload hash', () => {
    expect(() => signatureMessage({ ...base, payloadHash: 'ABC' })).toThrow('invalid payload hash');
    expect(() =>
      signatureMessage({ ...base, payloadHash: base.payloadHash.toUpperCase() }),
    ).toThrow('invalid payload hash');
  });

  it('rejects a bad nonce', () => {
    expect(() => signatureMessage({ ...base, nonce: 'a|b' })).toThrow('invalid nonce');
    expect(() => signatureMessage({ ...base, nonce: '' })).toThrow('invalid nonce');
  });

  it('rejects a bad decision', () => {
    expect(() => signatureMessage({ ...base, decision: 'maybe' as 'approve' })).toThrow(
      'invalid decision',
    );
  });

  it('rejects a key of the wrong length', () => {
    expect(() => approvalSignature(new Uint8Array(16), base)).toThrow('invalid approval key');
  });
});
