// The one way a link from the agent's text is opened: only http(s) and mailto, and only after the
// owner confirms the exact address. Used by Markdown links and the Sources row.
import { Alert, Linking } from 'react-native';

import { isSafeLink } from './markdown';

export function confirmOpen(href: string): void {
  if (!isSafeLink(href)) return;
  Alert.alert('Open link?', href, [
    { text: 'Cancel', style: 'cancel' },
    { text: 'Open', onPress: () => void Linking.openURL(href).catch(() => undefined) },
  ]);
}
