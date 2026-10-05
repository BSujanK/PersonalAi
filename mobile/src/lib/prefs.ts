// Small non-secret preferences. Stored in expo-secure-store to avoid another native dependency.
import * as SecureStore from 'expo-secure-store';

const PREFIX = 'personalai.pref.';

export async function getJson<T>(key: string, fallback: T): Promise<T> {
  try {
    const raw = await SecureStore.getItemAsync(PREFIX + key);
    return raw === null ? fallback : (JSON.parse(raw) as T);
  } catch {
    return fallback;
  }
}

export async function setJson(key: string, value: unknown): Promise<void> {
  await SecureStore.setItemAsync(PREFIX + key, JSON.stringify(value));
}
