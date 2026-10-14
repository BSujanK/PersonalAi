import { useEffect, useState } from 'react';

import { getMailSummary, type MailSummary } from './api';

export type MailSummaryState =
  | { status: 'loading' }
  | { status: 'ready'; summary: MailSummary }
  /** Any failure (model down, offline, bad payload): the screen quietly shows the plain mail. */
  | { status: 'failed' };

const LOADING: MailSummaryState = { status: 'loading' };

/**
 * Ask the agent for one mail's summary, once per mail. It runs beside the mail's own load, not
 * after it. A summary can take seconds, so there is no polling and no retry: a failure is final
 * until the screen is opened again. An answer for a mail the screen has moved on from is dropped.
 */
export function useMailSummary(account: string, id: string): MailSummaryState {
  const key = `${account}\n${id}`;
  const [settled, setSettled] = useState<{ key: string; state: MailSummaryState } | null>(null);

  useEffect(() => {
    let current = true;
    getMailSummary(account, id).then(
      ({ summary }) => {
        if (current) setSettled({ key, state: { status: 'ready', summary } });
      },
      () => {
        if (current) setSettled({ key, state: { status: 'failed' } });
      },
    );
    return () => {
      current = false;
    };
  }, [account, id, key]);

  return settled?.key === key ? settled.state : LOADING;
}
