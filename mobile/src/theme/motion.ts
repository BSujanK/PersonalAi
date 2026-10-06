import { cubicBezier } from 'react-native-reanimated';

// Motion tokens (animate-expo skill). Everything a finger drives is a spring; everything else is a
// short ease-out. Nothing here runs on the JS thread per frame.
export const motion = {
  /** Press feedback: near-imperceptible, because it happens tens of times a day. */
  pressMs: 120,
  pressScale: 0.97,
  /** Toggles, chips, a value flipping. */
  stateMs: 180,
  /** Content the user asked for and is waiting on (results, a decision outcome). */
  enterMs: 220,
  /** Distance the large title scrolls before the compact title takes over. */
  titleCollapse: 44,
} as const;

/**
 * Strong ease-out for UI entering or reacting. Never ease-in on UI.
 *
 * Built with Reanimated's cubicBezier(): CSS transitions on device reject the string form of a
 * cubic bezier. Kept OUT of `motion` on purpose: worklets copy every value they capture, and
 * capturing `motion` must never drag this class instance onto the UI thread (fatal
 * "Cannot copy value of type CubicBezierEasing"). `motion` stays plain numbers.
 */
export const easeOut = cubicBezier(0.23, 1, 0.32, 1);
