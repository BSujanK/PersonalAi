import type { ExpoConfig } from 'expo/config';

// Brand bitmaps (icon, adaptive layers, monochrome, splash, notification icon) are rendered from
// the spark geometry by scripts/render-brand.mjs.
const INK = '#07060B';
const VIOLET = '#8B5CF6';

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
  icon: './assets/icon.png',
  backgroundColor: INK,
  android: {
    package: 'com.bsujank.personalai',
    allowBackup: false,
    adaptiveIcon: {
      foregroundImage: './assets/adaptive-icon.png',
      backgroundImage: './assets/adaptive-icon-background.png',
      // Android 13+ themed icons.
      monochromeImage: './assets/adaptive-icon-monochrome.png',
      backgroundColor: INK,
    },
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
    // The small icon must be a white silhouette; Android tints it with `color`.
    ['expo-notifications', { icon: './assets/notification-icon.png', color: VIOLET }],
    [
      'expo-splash-screen',
      {
        image: './assets/splash-icon.png',
        imageWidth: 160,
        resizeMode: 'contain',
        backgroundColor: INK,
        dark: { image: './assets/splash-icon.png', backgroundColor: INK },
      },
    ],
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
