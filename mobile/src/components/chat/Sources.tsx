import { Text, View } from 'react-native';

import { confirmOpen } from '../../lib/confirmLink';
import { sourceHost, truncateTitle, type Source } from '../../lib/sources';
import { fontFamily, radius, space, type, useThemedStyles, type Palette } from '../../theme';
import { PressableScale } from '../ui';

const makeStyles = (p: Palette) => ({
  root: { gap: space.sm },
  label: { ...type.caption, color: p.textMuted },
  chips: { flexDirection: 'row' as const, flexWrap: 'wrap' as const, gap: space.sm },
  chip: {
    maxWidth: '100%' as const,
    minHeight: 32,
    justifyContent: 'center' as const,
    paddingHorizontal: space.sm + space.xs,
    paddingVertical: space.xs,
    borderRadius: radius.pill,
    backgroundColor: p.glass,
    borderWidth: 1,
    borderColor: p.glassBorder,
  },
  chipText: { ...type.footnote, color: p.textMuted, flexShrink: 1 },
  host: { fontFamily: fontFamily.bodySemiBold, color: p.accentText },
});

/**
 * The web pages an answer used, as small chips: the site and a shortened title. A tap goes
 * through the same "Open link?" confirmation as a link in the text. Nothing is shown when empty.
 */
export function Sources({ sources }: { sources: Source[] }) {
  const styles = useThemedStyles(makeStyles);
  if (sources.length === 0) return null;
  return (
    <View style={styles.root} testID="sources">
      <Text style={styles.label}>Sources</Text>
      <View style={styles.chips}>
        {sources.map((source) => {
          const host = sourceHost(source.url) ?? source.url;
          const title = truncateTitle(source.title);
          return (
            <PressableScale
              key={source.url}
              accessibilityRole="link"
              accessibilityLabel={`${host}, ${source.title}`}
              accessibilityHint="Asks before opening the page"
              hitSlop={{ top: 6, bottom: 6 }}
              onPress={() => confirmOpen(source.url)}
              style={styles.chip}
            >
              <Text numberOfLines={1} style={styles.chipText}>
                <Text style={styles.host}>{host}</Text>
                {title === host ? '' : ` · ${title}`}
              </Text>
            </PressableScale>
          );
        })}
      </View>
    </View>
  );
}
