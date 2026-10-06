import { fireEvent, render, screen } from '@testing-library/react-native';

import Files from '../../../app/(drawer)/files';
import { searchFiles } from '../../lib/api';

const mockNavigate = jest.fn();
jest.mock('expo-router', () => ({
  useRouter: () => ({ navigate: mockNavigate }),
  useNavigation: () => ({ toggleDrawer: jest.fn() }),
}));
jest.mock('../../lib/api', () => ({
  ...jest.requireActual('../../lib/api'),
  searchFiles: jest.fn(),
}));

jest.setTimeout(30_000);

beforeEach(() => {
  mockNavigate.mockReset();
  jest.mocked(searchFiles).mockReset();
  jest.mocked(searchFiles).mockResolvedValue({
    local: [
      {
        source: 'local',
        path: 'C:\\Users\\owner\\Documents\\itinerary.pdf',
        name: 'itinerary.pdf',
        size: 2048,
        modified: '2026-10-01T09:00:00Z',
      },
    ],
    drive: [
      {
        source: 'drive',
        account: 'me@example.com',
        id: 'f1',
        name: 'Lisbon notes',
        mime: 'text/plain',
        size: null,
        modified: null,
      },
    ],
    errors: [],
  });
});

async function search() {
  await render(<Files />);
  const field = screen.getByLabelText('Search files');
  await fireEvent.changeText(field, 'lisbon');
  await fireEvent(field, 'submitEditing');
  await screen.findByText('itinerary.pdf');
}

describe('Files', () => {
  it('lists laptop and Drive results', async () => {
    await search();
    expect(searchFiles).toHaveBeenCalledWith('lisbon');
    expect(screen.getByText('On this laptop')).toBeTruthy();
    expect(screen.getByText('Google Drive')).toBeTruthy();
    expect(screen.getByText('Lisbon notes')).toBeTruthy();
  });

  it('turns Send via mail and Share link into chat drafts that still need approval', async () => {
    await search();
    expect(screen.queryByLabelText('Send via mail')).toBeNull();
    await fireEvent.press(screen.getByLabelText('itinerary.pdf, on the laptop'));
    await fireEvent.press(screen.getByLabelText('Send via mail'));
    let call = mockNavigate.mock.calls[0][0] as { params: { d: string } };
    expect(call.params.d).toBe(
      'Email the local file C:\\Users\\owner\\Documents\\itinerary.pdf as an attachment to ',
    );

    await fireEvent.press(screen.getByLabelText('Lisbon notes, in Google Drive'));
    await fireEvent.press(screen.getByLabelText('Share link'));
    call = mockNavigate.mock.calls[1][0] as { params: { d: string } };
    expect(call.params.d).toContain('account me@example.com, file id f1');
    expect(call.params.d).toContain('anyone with the link');
  });

  it('says when a source is not configured', async () => {
    jest.mocked(searchFiles).mockResolvedValue({ local: [], drive: null, errors: [] });
    await render(<Files />);
    const field = screen.getByLabelText('Search files');
    await fireEvent.changeText(field, 'zz');
    await fireEvent(field, 'submitEditing');
    expect(await screen.findByText('No matches.')).toBeTruthy();
    expect(screen.getByText('Not configured on the laptop yet.')).toBeTruthy();
  });
});
