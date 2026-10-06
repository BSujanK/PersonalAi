import { useRouter } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import { Text, View } from 'react-native';
import Animated, { FadeIn } from 'react-native-reanimated';

import { Icon } from '../../src/components/Icon';
import { Screen } from '../../src/components/Screen';
import {
  Button,
  EmptyRow,
  ErrorText,
  ListRow,
  ListSection,
  Loading,
  SearchField,
} from '../../src/components/ui';
import { sendFileByMail, shareFileLink } from '../../src/lib/agentPrompts';
import { searchFiles, type FileHit, type FileSearch } from '../../src/lib/api';
import { openNewChat } from '../../src/lib/chatRoutes';
import { errorMessage, formatBytes, rowTime } from '../../src/lib/format';
import { motion, space, type, useTheme, useThemedStyles, type Palette } from '../../src/theme';

const DEBOUNCE_MS = 400;
const MIN_QUERY = 2;

const makeStyles = (p: Palette) => ({
  actions: {
    flexDirection: 'row' as const,
    flexWrap: 'wrap' as const,
    gap: space.sm,
    paddingTop: space.sm,
  },
  action: { flexGrow: 1, flexBasis: 130 },
  intro: { alignItems: 'center' as const, gap: space.sm, paddingVertical: space.xl },
  introTitle: { ...type.title3, color: p.text },
  introText: { ...type.subhead, color: p.textMuted, textAlign: 'center' as const },
});

const ACTIONS_ENTER = FadeIn.duration(motion.stateMs);

const keyOf = (f: FileHit) => (f.source === 'local' ? `l:${f.path}` : `d:${f.account}:${f.id}`);

function detail(f: FileHit): string {
  const parts = [
    f.size !== null ? formatBytes(f.size) : null,
    f.modified ? rowTime(f.modified) : null,
    f.source === 'local' ? f.path : f.account,
  ];
  return parts.filter(Boolean).join(' · ');
}

function FileRow({
  file,
  open,
  onToggle,
  onSend,
  onShare,
}: {
  file: FileHit;
  open: boolean;
  onToggle: () => void;
  onSend: () => void;
  onShare: () => void;
}) {
  const styles = useThemedStyles(makeStyles);
  return (
    <ListRow
      icon={file.source === 'local' ? 'hard-drive' : 'cloud'}
      title={file.name}
      subtitle={detail(file)}
      subtitleLines={open ? 4 : 1}
      onPress={onToggle}
      selected={open}
      accessibilityLabel={`${file.name}, ${file.source === 'local' ? 'on the laptop' : 'in Google Drive'}`}
      accessibilityHint={open ? 'Hides the actions' : 'Shows send and share actions'}
      accessory={null}
    >
      {open ? (
        <Animated.View entering={ACTIONS_ENTER} style={styles.actions}>
          <View style={styles.action}>
            <Button
              label="Send via mail"
              icon="send"
              tone="tinted"
              compact
              accessibilityHint="Starts a chat request to email this file. It needs your approval."
              onPress={onSend}
            />
          </View>
          <View style={styles.action}>
            <Button
              label="Share link"
              icon="link"
              tone="plain"
              compact
              accessibilityHint="Starts a chat request for a share link. It needs your approval."
              onPress={onShare}
            />
          </View>
        </Animated.View>
      ) : null}
    </ListRow>
  );
}

export default function Files() {
  const styles = useThemedStyles(makeStyles);
  const { palette } = useTheme();
  const router = useRouter();
  const [query, setQuery] = useState('');
  const [result, setResult] = useState<FileSearch | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [openKey, setOpenKey] = useState<string | null>(null);
  const seq = useRef(0);

  async function run(text: string) {
    const q = text.trim();
    const mine = ++seq.current;
    if (q.length < MIN_QUERY) {
      setResult(null);
      setBusy(false);
      return;
    }
    setBusy(true);
    try {
      const found = await searchFiles(q);
      if (mine !== seq.current) return; // a newer search started; drop this answer
      setResult(found);
      setError(null);
      setOpenKey(null);
    } catch (e) {
      if (mine === seq.current) setError(errorMessage(e));
    } finally {
      if (mine === seq.current) setBusy(false);
    }
  }

  useEffect(() => {
    const timer = setTimeout(() => void run(query), DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [query]);

  const send = (f: FileHit) => openNewChat(router, sendFileByMail(f));
  const share = (f: FileHit) => openNewChat(router, shareFileLink(f));

  function section(title: string, list: FileHit[] | null, failed: boolean) {
    return (
      <ListSection title={title} inset="icon">
        {failed ? <EmptyRow>Could not search here right now.</EmptyRow> : null}
        {!failed && list === null ? <EmptyRow>Not configured on the laptop yet.</EmptyRow> : null}
        {list?.length === 0 ? <EmptyRow>No matches.</EmptyRow> : null}
        {list?.map((f) => {
          const key = keyOf(f);
          return (
            <FileRow
              key={key}
              file={f}
              open={openKey === key}
              onToggle={() => setOpenKey(openKey === key ? null : key)}
              onSend={() => send(f)}
              onShare={() => share(f)}
            />
          );
        })}
      </ListSection>
    );
  }

  return (
    <Screen title="Files" subtitle="Laptop folders and Google Drive" menu>
      <SearchField
        accessibilityLabel="Search files"
        placeholder="Search files"
        value={query}
        onChangeText={setQuery}
        onSubmitEditing={() => void run(query)}
      />
      <ErrorText message={error} />
      {busy && !result ? <Loading /> : null}
      {result ? (
        <>
          {section('On this laptop', result.local, result.errors.includes('local'))}
          {section('Google Drive', result.drive, result.errors.includes('drive'))}
          <Text style={[type.footnote, { color: palette.textMuted }]}>
            Send and Share start a chat request. Nothing leaves your accounts until you approve it
            with your fingerprint.
          </Text>
        </>
      ) : !busy ? (
        <View style={styles.intro}>
          <Icon name="folder" size={32} color={palette.accentText} />
          <Text style={styles.introTitle}>Find a file</Text>
          <Text style={styles.introText}>
            Searches the folders you allowed on the laptop and your Google Drive. Pick a result to
            send it by mail or share a link.
          </Text>
        </View>
      ) : null}
    </Screen>
  );
}
