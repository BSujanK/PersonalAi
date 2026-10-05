package expo.modules.banksms

import android.content.Context
import android.content.Intent
import android.provider.AlarmClock
import android.provider.Telephony
import expo.modules.kotlin.exception.Exceptions
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition

class BankSmsModule : Module() {
  private val context: Context
    get() = appContext.reactContext ?: throw Exceptions.ReactContextLost()

  override fun definition() = ModuleDefinition {
    Name("BankSms")

    Function("setAllowedSenders") { senders: List<String> ->
      SmsQueue.setAllowed(context, senders)
    }

    AsyncFunction("scanInbox") { sinceMs: Double ->
      val allowed = SmsQueue.allowed(context)
      val found = mutableListOf<Triple<String, String, Long>>()
      val cursor = context.contentResolver.query(
        Telephony.Sms.Inbox.CONTENT_URI,
        arrayOf(Telephony.Sms.ADDRESS, Telephony.Sms.BODY, Telephony.Sms.DATE),
        "${Telephony.Sms.DATE} > ?",
        arrayOf(sinceMs.toLong().toString()),
        "${Telephony.Sms.DATE} ASC"
      )
      cursor?.use {
        while (it.moveToNext()) {
          val sender = it.getString(0) ?: continue
          if (!SmsFilter.isBank(sender, allowed)) continue
          found.add(Triple(sender, it.getString(1) ?: "", it.getLong(2)))
        }
      }
      SmsQueue.add(context, found)
    }

    AsyncFunction("peekQueue") { limit: Int ->
      SmsQueue.peek(context, limit).map {
        mapOf("id" to it.id, "sender" to it.sender, "body" to it.body, "received_at" to it.receivedAt)
      }
    }

    AsyncFunction("removeFromQueue") { ids: List<String> ->
      SmsQueue.remove(context, ids.toSet())
    }

    AsyncFunction("queueSize") {
      SmsQueue.size(context)
    }

    // Phone actions. Built natively so EXTRA_DAYS is the ArrayList<Integer> the clock app expects.
    // JS validates the values first; these run only for commands the owner approved.
    AsyncFunction("setAlarm") { hour: Int, minute: Int, label: String, days: List<Int>? ->
      val intent = Intent(AlarmClock.ACTION_SET_ALARM)
        .putExtra(AlarmClock.EXTRA_HOUR, hour)
        .putExtra(AlarmClock.EXTRA_MINUTES, minute)
        .putExtra(AlarmClock.EXTRA_MESSAGE, label)
        .putExtra(AlarmClock.EXTRA_SKIP_UI, true)
      if (!days.isNullOrEmpty()) intent.putExtra(AlarmClock.EXTRA_DAYS, ArrayList(days))
      launch(intent)
    }

    AsyncFunction("setTimer") { seconds: Int, label: String ->
      launch(
        Intent(AlarmClock.ACTION_SET_TIMER)
          .putExtra(AlarmClock.EXTRA_LENGTH, seconds)
          .putExtra(AlarmClock.EXTRA_MESSAGE, label)
          .putExtra(AlarmClock.EXTRA_SKIP_UI, true)
      )
    }
  }

  private fun launch(intent: Intent) {
    val activity = appContext.currentActivity
      ?: throw IllegalStateException("phone actions run only while the app is open")
    activity.startActivity(intent)
  }
}
