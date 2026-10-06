import { Text, View } from 'react-native';

import { space, type, useThemedStyles, type Palette } from '../theme';
import { Spark } from './brand/Spark';
import { PairForm } from './PairForm';
import { Screen } from './Screen';

const makeStyles = (p: Palette) => ({
  hero: { alignItems: 'center' as const, gap: space.md, paddingTop: space.xl },
  title: { ...type.largeTitle, color: p.text, textAlign: 'center' as const },
  subtitle: { ...type.callout, color: p.textMuted, textAlign: 'center' as const },
});

/** First run: the spark, one line of what this is, and the pairing form. */
export function PairScreen() {
  const styles = useThemedStyles(makeStyles);
  return (
    <Screen>
      <View style={styles.hero}>
        <Spark size={88} />
        <Text accessibilityRole="header" style={styles.title}>
          Pair your phone
        </Text>
        <Text style={styles.subtitle}>
          Connect to the PersonalAi agent on your laptop, over Tailscale only.
        </Text>
      </View>
      <PairForm />
    </Screen>
  );
}
