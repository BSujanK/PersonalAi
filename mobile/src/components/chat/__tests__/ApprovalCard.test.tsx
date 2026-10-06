import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import * as Clipboard from 'expo-clipboard';

import { decideApproval, getApproval, type Approval } from '../../../lib/api';
import { processDeviceCommands } from '../../../lib/deviceCommands';
import { signWithBiometrics } from '../../../lib/secureKeys';
import { previewVectors } from '../../../test/previewVectors';
import { ApprovalCard } from '../ApprovalCard';

jest.mock('../../../lib/api', () => ({
  ...jest.requireActual('../../../lib/api'),
  getApproval: jest.fn(),
  decideApproval: jest.fn(),
}));
jest.mock('../../../lib/secureKeys', () => ({
  ...jest.requireActual('../../../lib/secureKeys'),
  signWithBiometrics: jest.fn(),
}));
jest.mock('../../../lib/deviceCommands', () => ({ processDeviceCommands: jest.fn() }));

jest.mock('expo-clipboard', () => ({ setStringAsync: jest.fn().mockResolvedValue(true) }));

jest.setTimeout(30_000);

const ACTION_ID = 'a'.repeat(32);
const HASH = 'b'.repeat(64);
const PREVIEW = "Send 'Hi' to friend@example.com\n\nLunch?";

function approval(status: string, expiresInMs = 600_000): Approval {
  return {
    id: ACTION_ID,
    tool_name: 'send_email',
    preview: PREVIEW,
    payload_hash: HASH,
    nonce: 'nonce-1',
    status,
    created_at: new Date().toISOString(),
    expires_at: new Date(Date.now() + expiresInMs).toISOString(),
  };
}

beforeEach(() => {
  // Reset only our mocks: resetAllMocks would also wipe the asset and font mocks of jest-expo.
  for (const mock of [getApproval, decideApproval, signWithBiometrics, processDeviceCommands]) {
    jest.mocked(mock).mockReset();
  }
  jest.mocked(processDeviceCommands).mockResolvedValue(undefined as never);
});

describe('ApprovalCard', () => {
  it('shows the exact server preview for a pending action', async () => {
    jest.mocked(getApproval).mockResolvedValue(approval('pending'));
    await render(<ApprovalCard actionId={ACTION_ID} />);
    expect(await screen.findByText(PREVIEW)).toBeTruthy();
    expect(screen.getByLabelText('Approve this action')).toBeTruthy();
    expect(screen.getByLabelText('Reject this action')).toBeTruthy();
    expect(getApproval).toHaveBeenCalledWith(ACTION_ID);
  });

  it('summarises NEW and EXTERNAL recipients in the header of a mail proposal', async () => {
    const mailSend = previewVectors().mail_send;
    jest
      .mocked(getApproval)
      .mockResolvedValue({
        ...approval('pending'),
        tool_name: 'mail_send',
        preview: mailSend.preview,
      });
    await render(<ApprovalCard actionId={ACTION_ID} />);
    expect(await screen.findByText('2 NEW')).toBeTruthy();
    expect(screen.getByText('1 EXTERNAL')).toBeTruthy();
    expect(screen.getByLabelText('2 recipients you have never emailed')).toBeTruthy();
    expect(screen.getByLabelText('1 recipient outside your domains')).toBeTruthy();
    expect(screen.getByText(mailSend.preview)).toBeTruthy();
  });

  it('approve signs with biometrics over the stored hash and nonce, then posts the signature', async () => {
    jest.mocked(getApproval).mockResolvedValueOnce(approval('pending'));
    jest.mocked(getApproval).mockResolvedValue(approval('executed'));
    jest.mocked(signWithBiometrics).mockResolvedValue('c'.repeat(64));
    jest.mocked(decideApproval).mockResolvedValue({ id: ACTION_ID, status: 'executed' });
    await render(<ApprovalCard actionId={ACTION_ID} />);
    await fireEvent.press(await screen.findByLabelText('Approve this action'));

    await waitFor(() => expect(decideApproval).toHaveBeenCalledTimes(1));
    expect(signWithBiometrics).toHaveBeenCalledWith(
      { actionId: ACTION_ID, payloadHash: HASH, nonce: 'nonce-1', decision: 'approve' },
      expect.stringContaining('Approve'),
    );
    expect(decideApproval).toHaveBeenCalledWith(ACTION_ID, 'approve', {
      payload_hash: HASH,
      nonce: 'nonce-1',
      sig: 'c'.repeat(64),
    });
    // The biometric prompt came first: the signature is what authorises the post.
    const order = [
      jest.mocked(signWithBiometrics).mock.invocationCallOrder[0],
      jest.mocked(decideApproval).mock.invocationCallOrder[0],
    ];
    expect(order[0]).toBeLessThan(order[1]);
    expect(processDeviceCommands).toHaveBeenCalled();
    expect(await screen.findByText('Approved and done')).toBeTruthy();
    expect(screen.queryByLabelText('Approve this action')).toBeNull();
  });

  it('reject signs the reject decision and shows the result', async () => {
    jest.mocked(getApproval).mockResolvedValueOnce(approval('pending'));
    jest.mocked(getApproval).mockResolvedValue(approval('rejected'));
    jest.mocked(signWithBiometrics).mockResolvedValue('d'.repeat(64));
    jest.mocked(decideApproval).mockResolvedValue({ id: ACTION_ID, status: 'rejected' });
    await render(<ApprovalCard actionId={ACTION_ID} />);
    await fireEvent.press(await screen.findByLabelText('Reject this action'));

    await waitFor(() => expect(decideApproval).toHaveBeenCalledTimes(1));
    expect(signWithBiometrics).toHaveBeenCalledWith(
      expect.objectContaining({ decision: 'reject', actionId: ACTION_ID }),
      expect.any(String),
    );
    expect(decideApproval).toHaveBeenCalledWith(
      ACTION_ID,
      'reject',
      expect.objectContaining({ sig: 'd'.repeat(64) }),
    );
    expect(processDeviceCommands).not.toHaveBeenCalled();
    expect(await screen.findByText('Rejected. Nothing was sent.')).toBeTruthy();
  });

  it('sends nothing when the biometric prompt is cancelled', async () => {
    jest.mocked(getApproval).mockResolvedValue(approval('pending'));
    jest.mocked(signWithBiometrics).mockRejectedValue(new Error('User canceled'));
    await render(<ApprovalCard actionId={ACTION_ID} />);
    await fireEvent.press(await screen.findByLabelText('Approve this action'));

    expect(await screen.findByText('User canceled')).toBeTruthy();
    expect(decideApproval).not.toHaveBeenCalled();
    expect(screen.getByLabelText('Approve this action')).toBeTruthy(); // can try again
  });

  it('shows already-decided and expired actions without buttons', async () => {
    jest.mocked(getApproval).mockResolvedValue(approval('pending', -1000));
    await render(<ApprovalCard actionId={ACTION_ID} />);
    expect(await screen.findByText(/Expired/)).toBeTruthy();
    expect(screen.queryByLabelText('Approve this action')).toBeNull();
    expect(signWithBiometrics).not.toHaveBeenCalled();
  });

  it('offers a retry when the action cannot be loaded', async () => {
    jest.mocked(getApproval).mockRejectedValueOnce(new Error('network down'));
    jest.mocked(getApproval).mockResolvedValue(approval('pending'));
    await render(<ApprovalCard actionId={ACTION_ID} />);
    expect(await screen.findByText('Could not load this approval')).toBeTruthy();
    await fireEvent.press(screen.getByText('Try again'));
    expect(await screen.findByText(PREVIEW)).toBeTruthy();
  });

  it('shows an https share link from the result with a copy button', async () => {
    const link = 'https://drive.example.com/file/abc/view';
    jest.mocked(getApproval).mockResolvedValueOnce(approval('pending'));
    jest.mocked(getApproval).mockResolvedValue(approval('executed'));
    jest.mocked(signWithBiometrics).mockResolvedValue('c'.repeat(64));
    jest.mocked(decideApproval).mockResolvedValue({
      id: ACTION_ID,
      status: 'executed',
      result: { link, file_id: 'abc' },
    });
    await render(<ApprovalCard actionId={ACTION_ID} />);
    await fireEvent.press(await screen.findByLabelText('Approve this action'));

    const text = await screen.findByText(link);
    expect(text.props.selectable).toBe(true);
    await fireEvent.press(screen.getByLabelText('Copy link'));
    expect(Clipboard.setStringAsync).toHaveBeenCalledWith(link);
  });

  it('does not show a link that is not https', async () => {
    jest.mocked(getApproval).mockResolvedValueOnce(approval('pending'));
    jest.mocked(getApproval).mockResolvedValue(approval('executed'));
    jest.mocked(signWithBiometrics).mockResolvedValue('c'.repeat(64));
    jest.mocked(decideApproval).mockResolvedValue({
      id: ACTION_ID,
      status: 'executed',
      result: { link: 'javascript:alert(1)' },
    });
    await render(<ApprovalCard actionId={ACTION_ID} />);
    await fireEvent.press(await screen.findByLabelText('Approve this action'));
    expect(await screen.findByText('Approved and done')).toBeTruthy();
    expect(screen.queryByLabelText('Copy link')).toBeNull();
  });
});
