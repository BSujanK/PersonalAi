// Default Expo Metro config. With PERSONALAI_SCREENSHOTS=1 (web screenshot harness only), the
// API client, secure storage and the native bank-SMS module resolve to synthetic stand-ins in
// screenshots/, so the real screens render with made-up data and no agent. Never set for builds.
const path = require('path');
const { getDefaultConfig } = require('expo/metro-config');

const config = getDefaultConfig(__dirname);

if (process.env.PERSONALAI_SCREENSHOTS === '1') {
  const mocks = path.join(__dirname, 'screenshots');
  const swap = {
    [path.join(__dirname, 'src/lib/api.ts')]: path.join(mocks, 'mockApi.ts'),
    [path.join(__dirname, 'src/lib/secureKeys.ts')]: path.join(mocks, 'mockSecureKeys.ts'),
    [path.join(__dirname, 'modules/bank-sms/index.ts')]: path.join(mocks, 'mockBankSms.ts'),
  };
  config.watchFolders = [...(config.watchFolders ?? []), path.join(__dirname, '..', 'shared')];
  config.resolver.resolveRequest = (context, moduleName, platform) => {
    if (moduleName === 'expo-secure-store') {
      return { type: 'sourceFile', filePath: path.join(mocks, 'mockSecureStore.ts') };
    }
    const resolved = context.resolveRequest(context, moduleName, platform);
    const target = resolved.type === 'sourceFile' ? swap[resolved.filePath] : undefined;
    // The stand-ins import the real modules for their types and helpers.
    if (target && !context.originModulePath.startsWith(mocks)) {
      return { type: 'sourceFile', filePath: target };
    }
    return resolved;
  };
}

module.exports = config;
