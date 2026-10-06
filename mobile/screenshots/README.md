# Screenshot harness

Renders the real screens with react-native-web and synthetic data (made-up people, `example.com`,
fake account numbers), then captures them into `docs/ui/`. Nothing here ships in the app:
`metro.config.js` only swaps in these stand-ins when `PERSONALAI_SCREENSHOTS=1`.

```sh
PERSONALAI_SCREENSHOTS=1 npx expo export -p web --output-dir /tmp/personalai-web
node screenshots/capture.mjs /tmp/personalai-web ../docs/ui   # needs Playwright + Chromium
```

- `mockApi.ts`: the agent API, answered from fixtures. Approval previews come from
  `shared/test-vectors/action-previews.json`, the same vectors the server and app tests use.
- `mockSecureKeys.ts`, `mockSecureStore.ts`: a synthetic pairing (add `?unpaired` to the URL for
  the pairing screen). Biometric signing always fails here, so nothing can be approved.
- `mockBankSms.ts`: the native SMS module.

The brand bitmaps in `assets/` come from `scripts/render-brand.mjs` the same way.
