package expo.modules.banksms

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.security.MessageDigest

data class QueuedSms(val id: String, val sender: String, val body: String, val receivedAt: Long)

/**
 * App-private store for the sender allowlist and the queue of bank SMS waiting to be uploaded.
 * Only messages that passed [SmsFilter] are ever added. All access is serialised because the
 * receiver and the JS-facing module run on different threads.
 */
object SmsQueue {
  private const val PREFS = "personalai_bank_sms"
  private const val ALLOWED = "allowed"
  private const val QUEUE = "queue"
  private const val MAX_QUEUED = 5000

  private fun prefs(context: Context) =
    context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

  @Synchronized
  fun setAllowed(context: Context, senders: List<String>) {
    prefs(context).edit().putStringSet(ALLOWED, senders.map(SmsFilter::normalise).toSet()).commit()
  }

  @Synchronized
  fun allowed(context: Context): Set<String> =
    prefs(context).getStringSet(ALLOWED, emptySet()) ?: emptySet()

  private fun idOf(sender: String, body: String, receivedAt: Long): String {
    val digest = MessageDigest.getInstance("SHA-256").digest("$sender|$body|$receivedAt".toByteArray())
    return digest.joinToString("") { "%02x".format(it) }.take(32)
  }

  private fun read(context: Context): List<QueuedSms> {
    val raw = prefs(context).getString(QUEUE, null) ?: return emptyList()
    val array = JSONArray(raw)
    return List(array.length()) {
      val o = array.getJSONObject(it)
      QueuedSms(o.getString("id"), o.getString("sender"), o.getString("body"), o.getLong("received_at"))
    }
  }

  private fun write(context: Context, items: List<QueuedSms>) {
    val array = JSONArray()
    items.forEach {
      array.put(
        JSONObject()
          .put("id", it.id)
          .put("sender", it.sender)
          .put("body", it.body)
          .put("received_at", it.receivedAt)
      )
    }
    prefs(context).edit().putString(QUEUE, array.toString()).commit()
  }

  /** Append messages not already queued (same sender, body and timestamp). Returns how many were new. */
  @Synchronized
  fun add(context: Context, incoming: List<Triple<String, String, Long>>): Int {
    val queue = read(context).toMutableList()
    val known = queue.map { it.id }.toHashSet()
    var added = 0
    for ((sender, body, receivedAt) in incoming) {
      val id = idOf(sender, body, receivedAt)
      if (known.add(id)) {
        queue.add(QueuedSms(id, sender, body, receivedAt))
        added++
      }
    }
    if (added > 0) write(context, queue.takeLast(MAX_QUEUED))
    return added
  }

  @Synchronized
  fun peek(context: Context, limit: Int): List<QueuedSms> = read(context).take(limit)

  @Synchronized
  fun remove(context: Context, ids: Set<String>) {
    val queue = read(context)
    val kept = queue.filterNot { it.id in ids }
    if (kept.size != queue.size) write(context, kept)
  }

  @Synchronized
  fun size(context: Context): Int = read(context).size
}
