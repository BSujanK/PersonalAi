/* global jest */
// Reanimated and Worklets need their native runtimes; jest gets their official mocks instead.
jest.mock('react-native-worklets', () => require('react-native-worklets/src/mock'));
jest.mock('react-native-reanimated', () => {
  const mock = require('react-native-reanimated/mock');
  // The official mock predates useReducedMotion; tests run with full motion.
  // It also lacks the CSS easing factories; a plain stand-in is enough here. The real rule
  // (never a 'cubic-bezier' string) is guarded by src/theme/__tests__/motion.test.ts.
  const cubicBezier = (x1, y1, x2, y2) => ({ x1, y1, x2, y2 });
  return { ...mock, cubicBezier, useReducedMotion: () => false };
});
// Screen reads safe-area insets (floating tab bar space); tests render without a provider.
jest.mock(
  'react-native-safe-area-context',
  () => require('react-native-safe-area-context/jest/mock').default,
);
