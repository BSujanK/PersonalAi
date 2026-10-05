import { CameraView, useCameraPermissions } from 'expo-camera';
import { useRef, useState } from 'react';
import { StyleSheet, View } from 'react-native';

import { pair } from '../lib/api';
import { errorMessage } from '../lib/format';
import { usePairing } from '../lib/PairingContext';
import { savePairing } from '../lib/secureKeys';
import { normaliseServerUrl, parsePairingQr } from '../lib/serverUrl';
import { Body, Button, Caption, Card, ErrorText, TextField } from './ui';

const DEVICE_NAME = 'Android phone';

/** QR scan or manual entry. Never logs the code, token or approval key. */
export function PairForm() {
  const { reload } = usePairing();
  const [permission, requestPermission] = useCameraPermissions();
  const [scanning, setScanning] = useState(false);
  const [url, setUrl] = useState('');
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const handled = useRef(false);

  async function submit(serverUrl: string, pairingCode: string) {
    setBusy(true);
    setError(null);
    try {
      const base = normaliseServerUrl(serverUrl);
      const result = await pair(base, pairingCode, DEVICE_NAME);
      await savePairing({
        serverUrl: base,
        deviceId: result.device_id,
        token: result.token,
        approvalKey: result.approval_key,
      });
      setCode('');
      await reload();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
      handled.current = false;
    }
  }

  async function startScan() {
    setError(null);
    if (!permission?.granted && !(await requestPermission()).granted) {
      setError(
        'Camera permission is needed to scan the QR code. You can enter the details by hand instead.',
      );
      return;
    }
    handled.current = false;
    setScanning(true);
  }

  function onScanned(data: string) {
    if (handled.current) return;
    handled.current = true;
    setScanning(false);
    try {
      const scanned = parsePairingQr(data);
      void submit(scanned.url, scanned.code);
    } catch (e) {
      handled.current = false;
      setError(errorMessage(e));
    }
  }

  return (
    <View style={styles.wrap}>
      <Card>
        <Body>
          On the laptop run `python -m agent pair`, then scan the QR code it shows. Pairing needs a
          fingerprint or face unlock enrolled on this phone; there is no fallback.
        </Body>
      </Card>
      {scanning ? (
        <View style={styles.camera}>
          <CameraView
            style={StyleSheet.absoluteFill}
            facing="back"
            barcodeScannerSettings={{ barcodeTypes: ['qr'] }}
            onBarcodeScanned={({ data }) => onScanned(data)}
          />
        </View>
      ) : null}
      <Button
        label={scanning ? 'Cancel scan' : 'Scan pairing QR'}
        onPress={scanning ? () => setScanning(false) : () => void startScan()}
        disabled={busy}
      />
      <Caption>Or enter by hand</Caption>
      <TextField
        accessibilityLabel="Server address"
        placeholder="http://100.x.y.z:8765"
        autoCapitalize="none"
        autoCorrect={false}
        value={url}
        onChangeText={setUrl}
      />
      <TextField
        accessibilityLabel="Pairing code"
        placeholder="Pairing code"
        autoCapitalize="none"
        autoCorrect={false}
        secureTextEntry
        value={code}
        onChangeText={setCode}
      />
      <Button
        label="Pair"
        onPress={() => void submit(url.trim(), code.trim())}
        disabled={busy || !url || !code}
        tone="plain"
      />
      <ErrorText message={error} />
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: 12 },
  camera: { height: 280, borderRadius: 10, overflow: 'hidden' },
});
