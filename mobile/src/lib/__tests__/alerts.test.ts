import * as Notifications from 'expo-notifications';

import {
  checkAlerts,
  handleAlertResponse,
  isKindEnabled,
  newerThan,
  outcomeForResponse,
  routeForTarget,
  toContent,
  alertAccount,
} from '../alerts';
import { getAlertSettings, getNotifications, undoAutoEvent } from '../api';
import type { AlertItem, AlertSettings } from '../api';
import { getJson, setJson } from '../prefs';

jest.mock('expo-notifications', () => ({
  getPermissionsAsync: jest.fn(),
  requestPermissionsAsync: jest.fn(),
  scheduleNotificationAsync: jest.fn(),
  setNotificationChannelAsync: jest.fn(),
  setNotificationCategoryAsync: jest.fn(),
  AndroidImportance: { HIGH: 4 },
}));
jest.mock('../prefs', () => ({ getJson: jest.fn(), setJson: jest.fn() }));
jest.mock('../api', () => ({
  getNotifications: jest.fn(),
  getAlertSettings: jest.fn(),
  undoAutoEvent: jest.fn(),
}));

const mocked = <T extends (...args: never[]) => unknown>(fn: T) => fn as unknown as jest.Mock;
const scheduled = mocked(Notifications.scheduleNotificationAsync);

const ALL_ON: AlertSettings = {
  important_mail: true,
  deadlines: true,
  briefing: true,
  briefing_time: '07:30',
};

function alert(id: number, kind: AlertItem['kind'], target: AlertItem['target']): AlertItem {
  return {
    id,
    kind,
    title: `Title ${id}`,
    body: `Body ${id}`,
    created_at: '2026-10-06T04:00:00Z',
    target,
  };
}

const mailAlert = (id: number) =>
  alert(id, 'important_mail', { type: 'mail', account: 'main', message_id: `m${id}` });
const deadlineAlert = (id: number) => alert(id, 'deadline', { type: 'deadline', deadline_id: id });
const briefingAlert = (id: number) => alert(id, 'briefing', { type: 'today' });

function storedLastId(value: number | null) {
  mocked(getJson).mockResolvedValue(value);
}

beforeEach(() => {
  jest.resetAllMocks();
  mocked(Notifications.getPermissionsAsync).mockResolvedValue({ status: 'granted' });
  mocked(getAlertSettings).mockResolvedValue(ALL_ON);
});

describe('checkAlerts', () => {
  it('on first run stores the latest id and shows nothing', async () => {
    storedLastId(null);
    mocked(getNotifications).mockResolvedValue({
      items: [mailAlert(1), mailAlert(2)],
      latest_id: 2,
    });
    await checkAlerts();
    expect(getNotifications).toHaveBeenCalledWith(0);
    expect(setJson).toHaveBeenCalledWith('alerts.lastId', 2);
    expect(scheduled).not.toHaveBeenCalled();
  });

  it('later runs show only new alerts, oldest first, as local notifications', async () => {
    storedLastId(3);
    mocked(getNotifications).mockResolvedValue({
      items: [deadlineAlert(5), mailAlert(4)],
      latest_id: 5,
    });
    await checkAlerts();
    expect(getNotifications).toHaveBeenCalledWith(3);
    expect(scheduled).toHaveBeenCalledTimes(2);
    expect(scheduled.mock.calls[0][0]).toMatchObject({
      content: { title: 'Title 4', body: 'Body 4', data: { alertId: 4 } },
      trigger: null,
    });
    expect(scheduled.mock.calls[1][0].content.data.alertId).toBe(5);
    expect(setJson).toHaveBeenLastCalledWith('alerts.lastId', 5);
  });

  it('respects the per-type toggles but still moves past hidden alerts', async () => {
    storedLastId(0);
    mocked(getAlertSettings).mockResolvedValue({ ...ALL_ON, deadlines: false, briefing: false });
    mocked(getNotifications).mockResolvedValue({
      items: [mailAlert(1), deadlineAlert(2), briefingAlert(3)],
      latest_id: 3,
    });
    await checkAlerts();
    expect(scheduled).toHaveBeenCalledTimes(1);
    expect(scheduled.mock.calls[0][0].content.data.alertId).toBe(1);
    expect(setJson).toHaveBeenLastCalledWith('alerts.lastId', 3);
  });

  it('shows nothing without permission and does not replay later', async () => {
    storedLastId(0);
    mocked(Notifications.getPermissionsAsync).mockResolvedValue({ status: 'denied' });
    mocked(getNotifications).mockResolvedValue({ items: [mailAlert(1)], latest_id: 1 });
    await checkAlerts();
    expect(scheduled).not.toHaveBeenCalled();
    expect(setJson).toHaveBeenLastCalledWith('alerts.lastId', 1);
  });

  it('leaves the stored id alone when the agent cannot be reached', async () => {
    storedLastId(2);
    mocked(getNotifications).mockRejectedValue(new Error('offline'));
    await expect(checkAlerts()).rejects.toThrow('offline');
    expect(setJson).not.toHaveBeenCalled();
  });

  it('does nothing when there is nothing new', async () => {
    storedLastId(5);
    mocked(getNotifications).mockResolvedValue({ items: [], latest_id: 5 });
    await checkAlerts();
    expect(scheduled).not.toHaveBeenCalled();
    expect(setJson).not.toHaveBeenCalled();
  });
});

describe('helpers', () => {
  it('newerThan filters and sorts ascending', () => {
    const items = [mailAlert(9), mailAlert(3), mailAlert(7)];
    expect(newerThan(items, 4).map((i) => i.id)).toEqual([7, 9]);
  });

  it('isKindEnabled follows the settings and always allows calendar_added', () => {
    const off = { ...ALL_ON, important_mail: false, deadlines: false, briefing: false };
    expect(isKindEnabled('important_mail', off)).toBe(false);
    expect(isKindEnabled('deadline', off)).toBe(false);
    expect(isKindEnabled('briefing', off)).toBe(false);
    expect(isKindEnabled('calendar_added', off)).toBe(true);
    expect(isKindEnabled('briefing', ALL_ON)).toBe(true);
  });

  it('routes by target', () => {
    expect(routeForTarget({ type: 'mail', account: 'main', message_id: 'm1' })).toEqual({
      pathname: '/mail/[account]/[id]',
      params: { account: 'main', id: 'm1' },
    });
    expect(routeForTarget({ type: 'deadline', deadline_id: 4 })).toEqual({ pathname: '/today' });
    expect(routeForTarget({ type: 'today' })).toEqual({ pathname: '/today' });
    expect(routeForTarget(undefined)).toEqual({ pathname: '/today' });
  });

  it('gives only calendar_added alerts with an undo action the Undo category', () => {
    const added: AlertItem = {
      ...alert(8, 'calendar_added', { type: 'deadline', deadline_id: 12 }),
      actions: ['undo'],
    };
    expect(toContent(added)).toMatchObject({
      categoryIdentifier: 'calendar_added',
      data: { alertId: 8, deadlineId: 12 },
    });
    expect(toContent(deadlineAlert(2)).categoryIdentifier).toBeUndefined();
    expect(toContent({ ...added, actions: [] }).categoryIdentifier).toBeUndefined();
  });
});

describe('responses', () => {
  const response = (actionIdentifier: string, data: unknown) =>
    ({
      actionIdentifier,
      notification: { request: { content: { data } } },
    }) as unknown as Notifications.NotificationResponse;

  it('maps the undo action to an undo of that deadline', () => {
    expect(outcomeForResponse('undo', { deadlineId: 12, target: { type: 'today' } })).toEqual({
      type: 'undo',
      deadlineId: 12,
    });
  });

  it('does not undo without a numeric deadline id; a tap routes instead', () => {
    expect(outcomeForResponse('undo', { deadlineId: '12' }).type).toBe('route');
    expect(
      outcomeForResponse('expo.modules.notifications.actions.DEFAULT', {
        deadlineId: 12,
        target: { type: 'mail', account: 'main', message_id: 'm1' },
      }),
    ).toEqual({
      type: 'route',
      route: { pathname: '/mail/[account]/[id]', params: { account: 'main', id: 'm1' } },
    });
  });

  it('calls the undo endpoint for the undo action and does not navigate', async () => {
    mocked(undoAutoEvent).mockResolvedValue({ status: 'undone' });
    const navigate = jest.fn();
    await handleAlertResponse(response('undo', { deadlineId: 12 }), navigate);
    expect(undoAutoEvent).toHaveBeenCalledWith(12);
    expect(navigate).not.toHaveBeenCalled();
  });

  it('navigates on a default tap and does not undo', async () => {
    const navigate = jest.fn();
    await handleAlertResponse(
      response('expo.modules.notifications.actions.DEFAULT', { target: { type: 'today' } }),
      navigate,
    );
    expect(navigate).toHaveBeenCalledWith({ pathname: '/today' });
    expect(undoAutoEvent).not.toHaveBeenCalled();
  });
});

describe('every alert opens its source', () => {
  it('opens a mail by id, or by message_id from an older agent', () => {
    const route = {
      pathname: '/mail/[account]/[id]',
      params: { account: 'me@example.com', id: 'm1' },
    };
    expect(routeForTarget({ type: 'mail', account: 'me@example.com', id: 'm1' })).toEqual(route);
    expect(routeForTarget({ type: 'mail', account: 'me@example.com', message_id: 'm1' })).toEqual(
      route,
    );
  });

  it('opens the mail a deadline was found in; Classroom deadlines open Today', () => {
    expect(
      routeForTarget({
        type: 'deadline',
        deadline_id: 3,
        source: 'mail',
        account: 'college@example.edu',
        message_id: 'm9',
      }),
    ).toEqual({
      pathname: '/mail/[account]/[id]',
      params: { account: 'college@example.edu', id: 'm9' },
    });
    expect(
      routeForTarget({ type: 'deadline', deadline_id: 4, source: 'classroom', course_id: 'c1' }),
    ).toEqual({ pathname: '/today' });
  });

  it('opens the inbox for "more important mail"', () => {
    expect(routeForTarget({ type: 'inbox', account: 'me@example.com' })).toEqual({
      pathname: '/inbox',
    });
  });

  it('knows which account an alert came from', () => {
    const base = { id: 1, kind: 'deadline' as const, title: 't', body: 'b', created_at: 'x' };
    expect(
      alertAccount({ ...base, target: { type: 'today' }, source_account: 'a@example.com' }),
    ).toBe('a@example.com');
    expect(
      alertAccount({
        ...base,
        target: { type: 'deadline', deadline_id: 1, account: 'b@example.com' },
      }),
    ).toBe('b@example.com');
    expect(alertAccount({ ...base, target: { type: 'today' } })).toBeNull();
  });
});
