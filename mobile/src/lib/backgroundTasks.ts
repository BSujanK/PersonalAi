// Periodic SMS upload and alert check while the app is closed. Phone actions are NOT run here: Android blocks
// launching activities from the background, so those wait for the app to be in the foreground.
import * as BackgroundTask from 'expo-background-task';
import * as TaskManager from 'expo-task-manager';

import { checkAlerts } from './alerts';
import { flushSmsQueue } from './bankSms';

const SMS_FLUSH_TASK = 'personalai-sms-flush';
const MIN_INTERVAL_MINUTES = 15;

TaskManager.defineTask(SMS_FLUSH_TASK, async () => {
  try {
    const results = await Promise.allSettled([flushSmsQueue(), checkAlerts()]);
    return results.some((r) => r.status === 'rejected')
      ? BackgroundTask.BackgroundTaskResult.Failed
      : BackgroundTask.BackgroundTaskResult.Success;
  } catch {
    return BackgroundTask.BackgroundTaskResult.Failed;
  }
});

export async function registerBackgroundSync(): Promise<void> {
  if (await TaskManager.isTaskRegisteredAsync(SMS_FLUSH_TASK)) return;
  await BackgroundTask.registerTaskAsync(SMS_FLUSH_TASK, { minimumInterval: MIN_INTERVAL_MINUTES });
}
