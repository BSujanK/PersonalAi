import type { ExpoConfig } from 'expo/config';

// Firebase config is never committed. It is supplied at build time (env var or EAS file secret).
const googleServicesFile = process.env.GOOGLE_SERVICES_JSON;
const easProjectId = process.env.EAS_PROJECT_ID;

const config: ExpoConfig = {
  name: 'PersonalAi',
  slug: 'personalai',
  scheme: 'personalai',
  version: '0.1.0',
  orientation: 'portrait',
  userInterfaceStyle: 'automatic',
  android: {
    package: 'com.bsujank.personalai',
    allowBackup: false,
    permissions: [
      'android.permission.RECEIVE_SMS',
      'android.permission.READ_SMS',
      'android.permission.CAMERA',
      'android.permission.USE_BIOMETRIC',
      'android.permission.POST_NOTIFICATIONS',
      'com.android.alarm.permission.SET_ALARM',
    ],
    ...(googleServicesFile ? { googleServicesFile } : {}),
  },
  plugins: [
    'expo-router',
    'expo-secure-store',
    'expo-notifications',
    'expo-background-task',
    [
      'expo-camera',
      {
        recordAudioAndroid: false,
        cameraPermission: 'PersonalAi scans the pairing QR code shown on your laptop.',
      },
    ],
    ['expo-build-properties', { android: { usesCleartextTraffic: true } }],
  ],
  extra: {
    // Set to the EAS project id to enable push; without it the app relies on polling.
    ...(easProjectId ? { eas: { projectId: easProjectId } } : {}),
  },
};

export default config;
