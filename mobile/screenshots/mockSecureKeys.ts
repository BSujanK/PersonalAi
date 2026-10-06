/* eslint-disable import/export -- intentional: these stand-ins shadow the real exports. */
// Screenshot harness only: a synthetic pairing, unless the URL asks for the unpaired screen.
import type { StoredPairing } from '../src/lib/secureKeys';

// Re-export the real module, then shadow the functions the screens call: an explicit export
// takes precedence over `export *`, which is exactly the point here.
export * from '../src/lib/secureKeys';

const unpaired = () =>
  typeof location !== 'undefined' && new URLSearchParams(location.search).has('unpaired');

export async function loadPairing(): Promise<StoredPairing | null> {
  if (unpaired()) return null;
  return { token: 'synthetic', deviceId: '7f3a9c21e0b4', serverUrl: 'http://100.101.102.103:8765' };
}
export async function clearPairing(): Promise<void> {}
export async function signWithBiometrics(): Promise<string> {
  throw new Error('No biometrics in the screenshot harness.');
}
