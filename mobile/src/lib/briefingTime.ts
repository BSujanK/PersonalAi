// The morning briefing time is a 24-hour "HH:MM" string, validated the same way the agent does.
const BRIEFING_TIME = /^([01]\d|2[0-3]):[0-5]\d$/;

export const isValidBriefingTime = (value: string): boolean => BRIEFING_TIME.test(value);
