// Screenshot harness only: the native bank-SMS module, with two queued messages.
const BankSms = {
  setAllowedSenders: () => undefined,
  scanInbox: async () => 0,
  peekQueue: async () => [],
  removeFromQueue: async () => undefined,
  queueSize: async () => 2,
  setAlarm: async () => undefined,
  setTimer: async () => undefined,
};
export default BankSms;
