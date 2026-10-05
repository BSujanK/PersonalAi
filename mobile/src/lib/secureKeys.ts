// The two pairing secrets (CLAUDE.md rule 1).
// - Device token: expo-secure-store, readable whenever the phone is unlocked.
// - Approval key: expo-secure-store with requireAuthentication, so Android Keystore releases it
//   only after a biometric prompt. It is read for one signature and then zeroed. There is no
//   fallback to unauthenticated storage: pairing fails if biometrics are unavailable.
import * as SecureStore from 'expo-secure-store';

import { approvalSignature, decodeApprovalKey, type SignedFields } from './approvalSignature';

const TOKEN = 'personalai.device_token';
const APPROVAL_KEY = 'personalai.approval_key';
const DEVICE_ID = 'personalai.device_id';
const SERVER_URL = 'personalai.server_url';

const PLAIN: SecureStore.SecureStoreOptions = {
  keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
};

function guarded(prompt: string): SecureStore.SecureStoreOptions {
  return {
    keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
    requireAuthentication: true,
    authenticationPrompt: prompt,
  };
}

export class BiometricUnavailableError extends Error {
  constructor() {
    super('biometric authentication is not available on this device');
    this.name = 'BiometricUnavailableError';
  }
}

export class NotPairedError extends Error {
  constructor() {
    super('this phone is not paired');
    this.name = 'NotPairedError';
  }
}

export interface Pairing {
  serverUrl: string;
  deviceId: string;
  token: string;
  approvalKey: string; // unpadded base64url, exactly as /pair returned it
}

export interface StoredPairing {
  serverUrl: string;
  deviceId: string;
  token: string;
}

/** Store a fresh pairing. The approval key goes first, so a cancelled prompt stores nothing. */
export async function savePairing(pairing: Pairing): Promise<void> {
  if (!SecureStore.canUseBiometricAuthentication()) throw new BiometricUnavailableError();
  decodeApprovalKey(pairing.approvalKey).fill(0); // reject a malformed key before storing it
  await clearPairing();
  await SecureStore.setItemAsync(
    APPROVAL_KEY,
    pairing.approvalKey,
    guarded('Confirm to finish pairing'),
  );
  await SecureStore.setItemAsync(DEVICE_ID, pairing.deviceId, PLAIN);
  await SecureStore.setItemAsync(SERVER_URL, pairing.serverUrl, PLAIN);
  await SecureStore.setItemAsync(TOKEN, pairing.token, PLAIN);
}

export async function loadPairing(): Promise<StoredPairing | null> {
  const [token, deviceId, serverUrl] = await Promise.all([
    SecureStore.getItemAsync(TOKEN, PLAIN),
    SecureStore.getItemAsync(DEVICE_ID, PLAIN),
    SecureStore.getItemAsync(SERVER_URL, PLAIN),
  ]);
  if (!token || !deviceId || !serverUrl) return null;
  return { token, deviceId, serverUrl };
}

export async function clearPairing(): Promise<void> {
  await Promise.all(
    [TOKEN, APPROVAL_KEY, DEVICE_ID, SERVER_URL].map((key) => SecureStore.deleteItemAsync(key)),
  );
}

/**
 * Show the biometric prompt, read the approval key and sign one decision.
 * Throws if the prompt is cancelled or fails; nothing is signed in that case.
 */
export async function signWithBiometrics(fields: SignedFields, prompt: string): Promise<string> {
  const encoded = await SecureStore.getItemAsync(APPROVAL_KEY, guarded(prompt));
  if (!encoded) throw new NotPairedError();
  const key = decodeApprovalKey(encoded);
  try {
    return approvalSignature(key, fields);
  } finally {
    key.fill(0);
  }
}
