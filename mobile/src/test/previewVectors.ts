// Test-only: the synthetic approval previews in shared/test-vectors/action-previews.json. The
// server's test suite checks it still produces exactly these, so the phone's parser is tested
// against the real format.
import * as fs from 'fs';
import * as path from 'path';

interface Vector {
  tool: string;
  preview: string;
}

type Name = 'mail_send' | 'mail_reply' | 'share_anyone' | 'share_restricted' | 'upload';

export function previewVectors(): Record<Name, Vector> {
  const file = path.join(__dirname, '../../../shared/test-vectors/action-previews.json');
  return JSON.parse(fs.readFileSync(file, 'utf8')) as Record<Name, Vector>;
}
