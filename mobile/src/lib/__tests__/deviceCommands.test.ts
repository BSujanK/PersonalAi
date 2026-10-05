import * as Notifications from 'expo-notifications';

import { ackDeviceCommand, getDeviceCommands, OfflineError, type DeviceCommand } from '../api';
import BankSms from '../../../modules/bank-sms';
import { parseCommand, processDeviceCommands } from '../deviceCommands';

jest.mock('../secureKeys', () => ({ loadPairing: jest.fn() }));
jest.mock('../../../modules/bank-sms', () => ({
  __esModule: true,
  default: { setAlarm: jest.fn(), setTimer: jest.fn() },
}));
const prefs: Record<string, unknown> = {};
jest.mock('../prefs', () => ({
  getJson: jest.fn((key: string, fallback: unknown) =>
    Promise.resolve(key in prefs ? JSON.parse(JSON.stringify(prefs[key])) : fallback),
  ),
  setJson: jest.fn((key: string, value: unknown) => {
    prefs[key] = JSON.parse(JSON.stringify(value));
    return Promise.resolve();
  }),
}));
jest.mock('expo-notifications', () => ({
  scheduleNotificationAsync: jest.fn(),
  SchedulableTriggerInputTypes: { DATE: 'date' },
}));
jest.mock('../api', () => ({
  ...jest.requireActual('../api'),
  getDeviceCommands: jest.fn(),
  ackDeviceCommand: jest.fn(),
}));

const setAlarm = jest.mocked(BankSms.setAlarm);
const launch = jest.mocked(BankSms.setTimer);
const schedule = jest.mocked(Notifications.scheduleNotificationAsync);
const fetchCommands = jest.mocked(getDeviceCommands);
const ack = jest.mocked(ackDeviceCommand);

const FUTURE = new Date(Date.now() + 3_600_000).toISOString();
const PAST = new Date(Date.now() - 3_600_000).toISOString();

function command(kind: string, params: unknown, expires = FUTURE, id = 'c1'): DeviceCommand {
  return { id, kind, params, created_at: PAST, expires_at: expires };
}

beforeEach(() => {
  jest.clearAllMocks();
  setAlarm.mockReset();
  launch.mockReset();
  for (const key of Object.keys(prefs)) delete prefs[key];
  ack.mockResolvedValue({ id: 'c1', status: 'done' });
});

describe('parseCommand', () => {
  it('accepts valid alarms, timers and reminders', () => {
    expect(parseCommand('set_alarm', { hour: 6, minute: 30, label: 'Gym', days: [2, 4] })).toEqual({
      kind: 'set_alarm',
      hour: 6,
      minute: 30,
      label: 'Gym',
      days: [2, 4],
    });
    expect(parseCommand('set_alarm', { hour: 0, minute: 59, label: '' })).toMatchObject({
      days: null,
    });
    expect(parseCommand('set_timer', { seconds: 86_400, label: 'x' })).toMatchObject({
      seconds: 86_400,
    });
    expect(
      parseCommand('reminder', { at: '2030-01-01T09:00:00+05:30', text: 'Pay rent' }),
    ).toMatchObject({
      kind: 'reminder',
      text: 'Pay rent',
    });
  });

  it.each([
    ['unknown kind', 'format_disk', {}],
    ['hour 24', 'set_alarm', { hour: 24, minute: 0, label: 'x' }],
    ['negative minute', 'set_alarm', { hour: 1, minute: -1, label: 'x' }],
    ['fractional hour', 'set_alarm', { hour: 1.5, minute: 0, label: 'x' }],
    ['string hour', 'set_alarm', { hour: '6', minute: 0, label: 'x' }],
    ['long label', 'set_alarm', { hour: 1, minute: 0, label: 'x'.repeat(61) }],
    ['day 0', 'set_alarm', { hour: 1, minute: 0, label: 'x', days: [0] }],
    ['day 8', 'set_alarm', { hour: 1, minute: 0, label: 'x', days: [8] }],
    ['duplicate days', 'set_alarm', { hour: 1, minute: 0, label: 'x', days: [2, 2] }],
    ['zero seconds', 'set_timer', { seconds: 0, label: 'x' }],
    ['too many seconds', 'set_timer', { seconds: 86_401, label: 'x' }],
    ['reminder without offset', 'reminder', { at: '2030-01-01T09:00:00', text: 'x' }],
    ['reminder invalid date', 'reminder', { at: '2030-13-45T99:00:00Z', text: 'x' }],
    ['reminder long text', 'reminder', { at: '2030-01-01T09:00:00Z', text: 'x'.repeat(201) }],
    ['reminder empty text', 'reminder', { at: '2030-01-01T09:00:00Z', text: '' }],
    ['null params', 'set_timer', null],
  ])('rejects %s', (_name, kind, params) => {
    expect(parseCommand(kind, params)).toBeNull();
  });
});

describe('processDeviceCommands', () => {
  it('fires the alarm and acks done', async () => {
    fetchCommands.mockResolvedValue({
      commands: [command('set_alarm', { hour: 6, minute: 30, label: 'Gym', days: [2, 4] })],
    });
    await expect(processDeviceCommands()).resolves.toEqual({ done: 1, failed: 0 });
    expect(setAlarm).toHaveBeenCalledWith(6, 30, 'Gym', [2, 4]);
    expect(ack).toHaveBeenCalledWith('c1', 'done');
  });

  it('fires the timer', async () => {
    fetchCommands.mockResolvedValue({
      commands: [command('set_timer', { seconds: 300, label: 'Tea' })],
    });
    await processDeviceCommands();
    expect(launch).toHaveBeenCalledWith(300, 'Tea');
  });

  it('schedules a reminder notification at the given time', async () => {
    fetchCommands.mockResolvedValue({
      commands: [command('reminder', { at: FUTURE, text: 'Call home' })],
    });
    await processDeviceCommands();
    expect(schedule).toHaveBeenCalledWith({
      content: { title: 'Reminder', body: 'Call home' },
      trigger: { type: 'date', date: new Date(FUTURE) },
    });
    expect(ack).toHaveBeenCalledWith('c1', 'done');
  });

  it('acks failed for invalid, expired, past-reminder and throwing commands without side effects', async () => {
    fetchCommands.mockResolvedValue({
      commands: [
        command('set_alarm', { hour: 99, minute: 0, label: 'x' }, FUTURE, 'bad'),
        command('set_timer', { seconds: 60, label: 'x' }, PAST, 'expired'),
        command('reminder', { at: PAST, text: 'late' }, FUTURE, 'past'),
        command('mystery', {}, FUTURE, 'unknown'),
      ],
    });
    await expect(processDeviceCommands()).resolves.toEqual({ done: 0, failed: 4 });
    expect(launch).not.toHaveBeenCalled();
    expect(setAlarm).not.toHaveBeenCalled();
    expect(schedule).not.toHaveBeenCalled();
    expect(ack.mock.calls.map((c) => c[1])).toEqual(['failed', 'failed', 'failed', 'failed']);
  });

  it('acks failed when the intent launch throws', async () => {
    launch.mockRejectedValue(new Error('no clock app'));
    fetchCommands.mockResolvedValue({
      commands: [command('set_timer', { seconds: 60, label: 'x' })],
    });
    await expect(processDeviceCommands()).resolves.toEqual({ done: 0, failed: 1 });
    expect(ack).toHaveBeenCalledWith('c1', 'failed');
  });

  it('does nothing while offline', async () => {
    fetchCommands.mockRejectedValue(new OfflineError());
    await expect(processDeviceCommands()).resolves.toEqual({ done: 0, failed: 0 });
    expect(ack).not.toHaveBeenCalled();
  });

  it('never fires a command twice when its ack failed', async () => {
    fetchCommands.mockResolvedValue({
      commands: [command('set_alarm', { hour: 7, minute: 0, label: 'Wake' })],
    });
    ack.mockRejectedValueOnce(new OfflineError());
    await expect(processDeviceCommands()).resolves.toEqual({ done: 0, failed: 0 });
    expect(setAlarm).toHaveBeenCalledTimes(1);
    await expect(processDeviceCommands()).resolves.toEqual({ done: 1, failed: 0 });
    expect(setAlarm).toHaveBeenCalledTimes(1);
    expect(ack).toHaveBeenLastCalledWith('c1', 'done');
    expect(prefs.unacked_commands).toEqual({});
  });
});
