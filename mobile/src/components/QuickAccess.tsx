import { ScrollView, Text, useWindowDimensions, View } from 'react-native';

import {
  fontFamily,
  MAX_CHROME_SCALE,
  motion,
  radius,
  space,
  type,
  useTheme,
  useThemedStyles,
  type Palette,
} from '../theme';
import { Icon, type IconName } from './Icon';
import { COLUMN_MAX, PressableScale, Stagger } from './ui';

const GAP = space.sm + space.xs;
const CARD_HEIGHT = 132;

export interface QuickItem {
  key: string;
  icon: IconName;
  title: string;
  /** Second line: a live count or a short description. */
  detail: string;
  onPress: () => void;
  accessibilityHint?: string;
}

const makeStyles = (p: Palette) => ({
  row: { gap: GAP, paddingHorizontal: space.md },
  bleed: { marginHorizontal: -space.md },
  card: {
    height: CARD_HEIGHT,
    borderRadius: radius.card,
    padding: space.md - space.xs,
    justifyContent: 'space-between' as const,
    backgroundColor: p.surface,
    borderWidth: 1,
    borderColor: p.glassBorder,
  },
  tile: {
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: 'center' as const,
    justifyContent: 'center' as const,
    backgroundColor: p.accentSoft,
  },
  title: { ...type.headline, fontSize: 16, color: p.text },
  detail: { ...type.footnote, color: p.textMuted },
});

/**
 * "Quick Access": tall rounded cards in a row, three on screen and the rest a swipe away. Icon
 * top-left, a two-line label bottom-left.
 */
export function QuickAccess({ items }: { items: QuickItem[] }) {
  const styles = useThemedStyles(makeStyles);
  const { palette } = useTheme();
  const { width } = useWindowDimensions();
  const column = Math.min(width, COLUMN_MAX) - space.md * 2;
  // Three full cards, with a sliver of the fourth hinting there is more.
  const cardWidth = Math.floor((column - GAP * 2) / 3.15);
  return (
    <View style={styles.bleed}>
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.row}
        snapToInterval={cardWidth + GAP}
        decelerationRate="fast"
      >
        {items.map((item, i) => (
          <Stagger key={item.key} index={i}>
            <PressableScale
              accessibilityLabel={`${item.title}, ${item.detail}`}
              accessibilityHint={item.accessibilityHint}
              onPress={item.onPress}
              scaleTo={motion.pressScaleCard}
              style={[styles.card, { width: cardWidth }]}
            >
              <View style={styles.tile}>
                <Icon name={item.icon} size={19} color={palette.accentText} />
              </View>
              <View>
                <Text
                  numberOfLines={1}
                  style={styles.title}
                  maxFontSizeMultiplier={MAX_CHROME_SCALE}
                >
                  {item.title}
                </Text>
                <Text
                  numberOfLines={1}
                  style={[styles.detail, { fontFamily: fontFamily.body }]}
                  maxFontSizeMultiplier={MAX_CHROME_SCALE}
                >
                  {item.detail}
                </Text>
              </View>
            </PressableScale>
          </Stagger>
        ))}
      </ScrollView>
    </View>
  );
}
