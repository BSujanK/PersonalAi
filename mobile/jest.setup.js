/* global jest */
// Reanimated and Worklets need their native runtimes; jest gets their official mocks instead.
jest.mock('react-native-worklets', () => require('react-native-worklets/src/mock'));
jest.mock('react-native-reanimated', () => {
  const mock = require('react-native-reanimated/mock');
  // The official mock predates useReducedMotion; tests run with full motion.
  return { ...mock, useReducedMotion: () => false };
});
