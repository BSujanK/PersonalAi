package expo.modules.banksms

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.provider.Telephony

/** Queues incoming SMS from bank senders. Anything else is dropped without being stored. */
class SmsReceiver : BroadcastReceiver() {
  override fun onReceive(context: Context, intent: Intent) {
    if (intent.action != Telephony.Sms.Intents.SMS_RECEIVED_ACTION) return
    val parts = Telephony.Sms.Intents.getMessagesFromIntent(intent)
    if (parts.isNullOrEmpty()) return
    val sender = parts[0].originatingAddress ?: return
    if (!SmsFilter.isBank(sender, SmsQueue.allowed(context))) return
    // Multipart messages arrive as several PDUs from one sender; join them in order.
    val body = parts.joinToString("") { it.messageBody ?: "" }
    if (SmsFilter.isOtp(body)) return
    SmsQueue.add(context, listOf(Triple(sender, body, parts[0].timestampMillis)))
  }
}
