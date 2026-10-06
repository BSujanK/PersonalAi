import { memo, useEffect, useMemo, useState } from 'react';
import { View } from 'react-native';
import Animated, { FadeIn, useReducedMotion } from 'react-native-reanimated';

import { nextRevealLength, splitSettled, tailWords } from '../../lib/streamText';
import { type, useThemedStyles, type Palette } from '../../theme';
import { Markdown } from './Markdown';

/** A new word fades in over this long; opacity only, run by Reanimated on the UI thread. */
const WORD_FADE_MS = 160;
/** A frame gap longer than this (the app was in the background) counts as this much. */
const MAX_FRAME_MS = 100;
// Built once: a layout animation is a plain config object, never rebuilt per render.
const WORD_IN = FadeIn.duration(WORD_FADE_MS);

const makeStyles = (p: Palette) => ({
  root: { gap: 10 },
  tail: { flexDirection: 'row' as const, flexWrap: 'wrap' as const },
  word: { ...type.body, color: p.text },
  // A newline inside the open block: a zero-height, full-width item forces the next word down.
  lineBreak: { width: '100%' as const, height: 0 },
});

/** The open tail as plain words; only words that newly appear fade in. */
const Tail = memo(function Tail({ text, base }: { text: string; base: number }) {
  const styles = useThemedStyles(makeStyles);
  const reduced = useReducedMotion();
  const words = useMemo(() => tailWords(text, base), [text, base]);
  return (
    <View style={styles.tail} accessible accessibilityLabel={text} testID="stream-tail">
      {words.map((w) =>
        w.text === '\n' ? (
          <View key={w.key} style={styles.lineBreak} />
        ) : (
          <Animated.Text key={w.key} entering={reduced ? undefined : WORD_IN} style={styles.word}>
            {w.text}
          </Animated.Text>
        ),
      )}
    </View>
  );
});

/**
 * The assistant's reply while it is being written. Tokens arrive in bursts; this reveals them a
 * word at a time on animation frames, at a pace that speeds up as the backlog grows. Finished
 * Markdown blocks render once as Markdown; only the open tail is plain text, so a half-written
 * list or table never flickers. Once the stream ends and the reveal catches up, the whole reply
 * is ordinary Markdown.
 */
function StreamingTextImpl({ text, streaming }: { text: string; streaming: boolean }) {
  const styles = useThemedStyles(makeStyles);
  // A reply loaded from history is shown whole; only a live one is revealed.
  const [shown, setShown] = useState(() => (streaming ? 0 : text.length));
  const behind = shown < text.length;

  useEffect(() => {
    if (!behind) return undefined;
    let frame = 0;
    let last: number | null = null;
    const tick = (now: number) => {
      const elapsed = last === null ? 16 : Math.min(MAX_FRAME_MS, now - last);
      last = now;
      setShown((s) => nextRevealLength(s, text, elapsed));
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [behind, text]);

  if (!behind && !streaming) return <Markdown text={text} />;

  const visible = text.slice(0, Math.min(shown, text.length));
  const { settled, tail } = splitSettled(visible);
  const open = tail.trimStart();
  return (
    <View style={styles.root}>
      {settled.trim() ? <Markdown text={settled} /> : null}
      {open.trim() ? (
        <Tail text={open} base={settled.length + tail.length - open.length} />
      ) : null}
    </View>
  );
}

export const StreamingText = memo(StreamingTextImpl);
