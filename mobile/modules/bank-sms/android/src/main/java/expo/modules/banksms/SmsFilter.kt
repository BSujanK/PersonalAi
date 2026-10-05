package expo.modules.banksms

import java.util.Locale

/** Mirrors normalize_sender and the BOB rule in the server (finance/sms_parsers/common.py). */
object SmsFilter {
  private val PREFIX = Regex("^[A-Z]{2}-")
  private val SUFFIX = Regex("-[STPG]$")
  private val NAME = Regex("^[A-Z0-9]{3,11}$")
  private val OTP = Regex(
    "\\b(?:otp|one[\\s-]*time\\s*pass(?:word|code)?|do\\s*not\\s*share|never\\s*share" +
      "|verification\\s*code|cvv)\\b",
    RegexOption.IGNORE_CASE
  )

  fun normalise(sender: String): String =
    sender.trim().uppercase(Locale.ROOT).replaceFirst(PREFIX, "").replaceFirst(SUFFIX, "")

  /** DLT-style header: 3 to 11 letters/digits with at least two letters. Never a phone number. */
  fun isValidName(name: String): Boolean =
    NAME.matches(name) && name.count { it in 'A'..'Z' } >= 2

  fun isBank(sender: String, allowed: Set<String>): Boolean {
    val name = normalise(sender)
    if (!isValidName(name)) return false
    return name.startsWith("BOB") || name in allowed
  }

  /** Mirrors _OTP in the server (finance/sms_parsers/common.py). OTP bodies are never stored. */
  fun isOtp(body: String): Boolean = OTP.containsMatchIn(body)
}
