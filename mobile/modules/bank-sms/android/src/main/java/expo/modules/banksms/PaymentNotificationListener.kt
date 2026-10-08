package expo.modules.banksms

import android.app.Notification
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification

/**
 * Queues payment notifications from three payment apps, for UPI payments the bank sends no SMS for.
 * The package allowlist is fixed here on purpose: JS and the server cannot widen it. A notification
 * from any other package is dropped before a single field of it is read. Titles and bodies are never
 * logged.
 */
class PaymentNotificationListener : NotificationListenerService() {
  override fun onListenerConnected() {
    // Pick up what was posted while the listener was unbound.
    try {
      capture(activeNotifications.orEmpty().asList())
    } catch (_: Exception) {
      // Deliberately silent, as in capture; the list is also unavailable if access was just revoked.
    }
  }

  override fun onNotificationPosted(sbn: StatusBarNotification?) {
    if (sbn != null) capture(listOf(sbn))
  }

  private fun capture(notifications: List<StatusBarNotification>) {
    try {
      val found = notifications.mapNotNull { toMessage(it) }
      if (found.isNotEmpty()) SmsQueue.add(applicationContext, found)
    } catch (_: Exception) {
      // Deliberately silent: logging here could expose a notification's text.
    }
  }

  private fun toMessage(sbn: StatusBarNotification): Triple<String, String, Long>? {
    val sender = SENDERS[sbn.packageName] ?: return null
    val notification = sbn.notification ?: return null
    if ((notification.flags and (Notification.FLAG_GROUP_SUMMARY or Notification.FLAG_ONGOING_EVENT)) != 0) {
      return null
    }
    val extras = notification.extras ?: return null
    val title = extras.getCharSequence(Notification.EXTRA_TITLE)?.toString().orEmpty()
    val text = extras.getCharSequence(Notification.EXTRA_TEXT)?.toString().orEmpty()
    val big = extras.getCharSequence(Notification.EXTRA_BIG_TEXT)?.toString().orEmpty()
    val body = "$title\n${if (big.length > text.length) big else text}".trim().take(MAX_BODY)
    if (SmsFilter.isOtp(body) || !AMOUNT.containsMatchIn(body)) return null
    return Triple(sender, body, sbn.postTime)
  }

  private companion object {
    const val MAX_BODY = 2000

    /** Package name to the sender label the server expects. Not configurable. */
    val SENDERS = mapOf(
      "com.phonepe.app" to "APP-PHONEPE",
      "com.google.android.apps.nbu.paisa.user" to "APP-GPAY",
      "com.bankofbaroda.mconnect" to "APP-BOBWORLD"
    )

    /** A rupee amount: a currency marker followed by a digit. */
    val AMOUNT = Regex("""(?:₹|\b(?:Rs\.?|INR))\s?\d""")
  }
}
