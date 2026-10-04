import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'com.pocketdl.app',
  appName: 'PocketDL',
  webDir: 'dist',
  server: {
    cleartext: true
  }
};

export default config;
