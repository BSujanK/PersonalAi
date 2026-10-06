// One haptic per user action, fired with the visual it belongs to, never as the only feedback.
// Haptics are silent on many Android phones and can be off system-wide, so failures are ignored.
import * as Haptics from 'expo-haptics';

const quiet = (p: Promise<void>) => void p.catch(() => undefined);

export const haptics = {
  /** A value ticked over: segmented control, a picker choice. */
  selection: () => quiet(Haptics.selectionAsync()),
  /** An action committed and the agent confirmed it. */
  success: () => quiet(Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success)),
  /** The agent refused or the action failed. */
  error: () => quiet(Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error)),
  /** Something landed: a link copied, a destructive choice confirmed. */
  impact: () => quiet(Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light)),
};
