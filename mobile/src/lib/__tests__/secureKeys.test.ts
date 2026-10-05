import fs from 'fs';
import path from 'path';

import * as SecureStore from 'expo-secure-store';

import {
  BiometricUnavailableError,
  NotPairedError,
  savePairing,
  signWithBiometrics,
} from '../secureKeys';

jest.mock('expo-secure-store', () => ({
  WHEN_UNLOCKED_THIS_DEVICE_ONLY: 'when_unlocked_this_device_only',
  canUseBiometricAuthentication: jest.fn(),
  setItemAsync: jest.fn(),
  getItemAsync: jest.fn(),
  deleteItemAsync: jest.fn(),
}));

const store = jest.mocked(SecureStore);

const vectors = JSON.parse(
  fs.readFileSync(
    path.join(__dirname, '../../../../shared/test-vectors/approval-signature.json'),
    'utf8',
  ),
) as {
  approval_key_b64url: string;
  cases: {
    action_id: string;
    payload_hash: string;
    nonce: string;
    decision: 'approve' | 'reject';
    sig: string;
  }[];
};
const vector = vectors.cases[0];
const fields = {
  actionId: vector.action_id,
  payloadHash: vector.payload_hash,
  nonce: vector.nonce,
  decision: vector.decision,
};

const pairing = {
  serverUrl: 'http://100.64.0.1:8765',
  deviceId: 'dev1',
  token: 'tok',
  approvalKey: vectors.approval_key_b64url,
};

beforeEach(() => {
  jest.resetAllMocks();
});

describe('savePairing', () => {
  it('throws and stores nothing when biometrics are unavailable', async () => {
    store.canUseBiometricAuthentication.mockReturnValue(false);
    await expect(savePairing(pairing)).rejects.toBeInstanceOf(BiometricUnavailableError);
    expect(store.setItemAsync).not.toHaveBeenCalled();
  });

  it('stores the approval key with requireAuthentication', async () => {
    store.canUseBiometricAuthentication.mockReturnValue(true);
    await savePairing(pairing);
    const keyCall = store.setItemAsync.mock.calls.find(
      ([, value]) => value === pairing.approvalKey,
    );
    expect(keyCall?.[2]).toMatchObject({ requireAuthentication: true });
    const tokenCall = store.setItemAsync.mock.calls.find(([, value]) => value === 'tok');
    expect(tokenCall?.[2]).not.toHaveProperty('requireAuthentication');
  });

  it('rejects a malformed approval key before storing anything', async () => {
    store.canUseBiometricAuthentication.mockReturnValue(true);
    await expect(savePairing({ ...pairing, approvalKey: 'short' })).rejects.toThrow(
      'invalid approval key',
    );
    expect(store.setItemAsync).not.toHaveBeenCalled();
  });
});

describe('signWithBiometrics', () => {
  it('reads with requireAuthentication and returns the vector signature', async () => {
    store.getItemAsync.mockResolvedValue(vectors.approval_key_b64url);
    await expect(signWithBiometrics(fields, 'Approve: test')).resolves.toBe(vector.sig);
    expect(store.getItemAsync).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        requireAuthentication: true,
        authenticationPrompt: 'Approve: test',
      }),
    );
  });

  it('propagates a cancelled prompt and produces no signature', async () => {
    store.getItemAsync.mockRejectedValue(new Error('User canceled the authentication'));
    await expect(signWithBiometrics(fields, 'Approve: test')).rejects.toThrow('canceled');
  });

  it('throws NotPairedError when no key is stored', async () => {
    store.getItemAsync.mockResolvedValue(null);
    await expect(signWithBiometrics(fields, 'x')).rejects.toBeInstanceOf(NotPairedError);
  });
});
