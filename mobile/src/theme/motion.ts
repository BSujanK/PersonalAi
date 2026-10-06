import { cubicBezier, Easing } from 'react-native-reanimated';

// Motion tokens (animate-expo skill). Everything a finger drives is a spring; everything else is a
// short ease-out. Nothing here runs on the JS thread per frame.
//
// `motion` holds plain numbers ONLY: worklets copy every value they capture, so a spring config
// is built from these numbers at the call site, never stored here as an object.
export const motion = {
  /** Press feedback: near-imperceptible, because it happens tens of times a day. */
  pressMs: 120,
  pressScale: 0.97,
  /** Larger cards scale a touch less, so the press reads as weight, not a jump. */
  pressScaleCard: 0.98,
  /** Press spring: critically damped, so a quick tap never wobbles. */
  pressSpringMs: 220,
  pressSpringDamping: 1,
  /** Toggles, chips, a value flipping. */
  stateMs: 180,
  /** Content the user asked for and is waiting on (results, a decision outcome). */
  enterMs: 240,
  /** Delay between rows of a list entering; capped so a long list never feels slow. */
  staggerMs: 40,
  staggerMax: 8,
  /** Rows rise this far as they fade in. */
  enterRise: 10,
  /** The hero figure counts up once, on first load. */
  countUpMs: 900,
  /** The tab pill follows the finger's choice with a little momentum. */
  tabSpringMs: 380,
  tabSpringDamping: 0.82,
  /** One turn of the spark while the agent is thinking. Slow: it is ambient, not urgent. */
  sparkTurnMs: 2800,
  /** One run of the wave round the spark's rays while thinking. */
  sparkPulseMs: 1400,
  /** The quick settle back to rest when a reply finishes. */
  settleMs: 420,
  /** Cold-launch intro: the mark spins in and settles, glows, then glides into the header. */
  introSpinMs: 900,
  introFadeInMs: 420,
  introGlowMs: 520,
  introGlideMs: 480,
  /** Under Reduce Motion the intro is the still mark and a short fade. */
  introFadeMs: 240,
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

/** On-screen movement (a value morphing in place). Same rules as `easeOut`. */
export const easeInOut = cubicBezier(0.77, 0, 0.175, 1);

/**
 * The same strong ease-out for withTiming() (shared-value animations). withTiming needs Reanimated's
 * worklet easing; the cubicBezier() object above is for CSS transitions only and crashes the UI
 * thread if a timing animation carries it (guarded in __tests__/motion.test.ts).
 */
export const timingEaseOut = Easing.bezier(0.23, 1, 0.32, 1);

/** Constant motion (a loop): the spark's turn and its ray wave. withTiming only. */
export const timingLinear = Easing.linear;

/** Breathing and the ray reveal: soft at both ends. withTiming only. */
export const timingSine = Easing.inOut(Easing.sin);
