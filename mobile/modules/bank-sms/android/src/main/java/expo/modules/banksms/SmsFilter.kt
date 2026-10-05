package expo.modules.banksms

import java.util.Locale

/** Mirrors normalize_sender and the BOB rule in the server (finance/sms_parsers/common.py). */
object SmsFilter {
  private val PREFIX = Regex("^[A-Z]{2}-")
  private val SUFFIX = Regex("-[STPG]$")

  fun normalise(sender: String): String =
    sender.trim().uppercase(Locale.ROOT).replaceFirst(PREFIX, "").replaceFirst(SUFFIX, "")

  fun isBank(sender: String, allowed: Set<String>): Boolean {
    val name = normalise(sender)
    return name.startsWith("BOB") || name in allowed
  }
}
