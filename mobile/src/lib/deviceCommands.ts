// Phone actions the owner approved on the laptop: alarms, timers and reminders. Every command is
// validated strictly here, whatever the server says, before it touches an Android intent.
import * as Notifications from 'expo-notifications';

import BankSms from '../../modules/bank-sms';
import { ackDeviceCommand, getDeviceCommands, OfflineError, type DeviceCommand } from './api';
import { getJson, setJson } from './prefs';

export type ParsedCommand =
  | { kind: 'set_alarm'; hour: number; minute: number; label: string; days: number[] | null }
  | { kind: 'set_timer'; seconds: number; label: string }
  | { kind: 'reminder'; at: Date; text: string };

const MAX_LABEL = 60;
const MAX_REMINDER = 200;
const MAX_TIMER_SECONDS = 86_400;
const ISO_WITH_OFFSET = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$/;

function intIn(value: unknown, min: number, max: number): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= min && value <= max;
}

function text(value: unknown, max: number): value is string {
  return typeof value === 'string' && value.length <= max;
}

function parseDays(value: unknown): number[] | null | undefined {
  if (value === undefined || value === null) return null;
  if (!Array.isArray(value) || value.length > 7) return undefined;
  if (!value.every((d) => intIn(d, 1, 7)) || new Set(value).size !== value.length) return undefined;
  return value as number[];
}

/** Return the command in typed form, or null if the kind is unknown or any value is out of range. */
export function parseCommand(kind: string, params: unknown): ParsedCommand | null {
  if (typeof params !== 'object' || params === null) return null;
  const p = params as Record<string, unknown>;
  if (kind === 'set_alarm') {
    const days = parseDays(p.days);
    if (!intIn(p.hour, 0, 23) || !intIn(p.minute, 0, 59) || !text(p.label, MAX_LABEL)) return null;
    if (days === undefined) return null;
    return { kind, hour: p.hour, minute: p.minute, label: p.label, days };
  }
  if (kind === 'set_timer') {
    if (!intIn(p.seconds, 1, MAX_TIMER_SECONDS) || !text(p.label, MAX_LABEL)) return null;
    return { kind, seconds: p.seconds, label: p.label };
  }
  if (kind === 'reminder') {
    if (!text(p.text, MAX_REMINDER) || p.text.length === 0) return null;
    if (typeof p.at !== 'string' || !ISO_WITH_OFFSET.test(p.at)) return null;
    const at = new Date(p.at);
    return Number.isNaN(at.getTime()) ? null : { kind, at, text: p.text };
  }
  return null;
}

async function execute(command: ParsedCommand, now: Date): Promise<void> {
  if (command.kind === 'set_alarm') {
    await BankSms.setAlarm(command.hour, command.minute, command.label, command.days);
  } else if (command.kind === 'set_timer') {
    await BankSms.setTimer(command.seconds, command.label);
  } else {
    if (command.at <= now) throw new Error('reminder time is in the past');
    await Notifications.scheduleNotificationAsync({
      content: { title: 'Reminder', body: command.text },
      trigger: { type: Notifications.SchedulableTriggerInputTypes.DATE, date: command.at },
    });
  }
}

async function run(command: DeviceCommand, now: Date): Promise<'done' | 'failed'> {
  if (Date.parse(command.expires_at) <= now.getTime()) return 'failed';
  const parsed = parseCommand(command.kind, command.params);
  if (!parsed) return 'failed';
  try {
    await execute(parsed, now);
    return 'done';
  } catch {
    return 'failed';
  }
}

export interface CommandSummary {
  done: number;
  failed: number;
}

let inFlight: Promise<CommandSummary> | null = null;

/**
 * Fetch and run pending commands. Foreground only: Android blocks launching activities from the
 * background. Concurrent calls share one run so a command is never executed twice.
 */
export function processDeviceCommands(): Promise<CommandSummary> {
  inFlight ??= runPending().finally(() => {
    inFlight = null;
  });
  return inFlight;
}

// Commands that ran but whose ack has not reached the server yet. A command found here is only
// re-acknowledged on the next run, never fired a second time.
const UNACKED = 'unacked_commands';
type Unacked = Record<string, 'done' | 'failed'>;

async function runPending(): Promise<CommandSummary> {
  const summary: CommandSummary = { done: 0, failed: 0 };
  let commands: DeviceCommand[];
  try {
    commands = (await getDeviceCommands()).commands;
  } catch (error) {
    if (error instanceof OfflineError) return summary;
    throw error;
  }
  const unacked = await getJson<Unacked>(UNACKED, {});
  const queued = new Set(commands.map((c) => c.id));
  for (const id of Object.keys(unacked)) if (!queued.has(id)) delete unacked[id];
  try {
    for (const command of commands) {
      const earlier = unacked[command.id];
      const result = earlier ?? (await run(command, new Date()));
      if (earlier === undefined) {
        unacked[command.id] = result;
        await setJson(UNACKED, unacked);
      }
      try {
        await ackDeviceCommand(command.id, result);
      } catch (error) {
        if (error instanceof OfflineError) return summary;
        throw error;
      }
      delete unacked[command.id];
      summary[result === 'done' ? 'done' : 'failed'] += 1;
    }
  } finally {
    await setJson(UNACKED, unacked);
  }
  return summary;
}
