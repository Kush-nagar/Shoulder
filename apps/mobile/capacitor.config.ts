import type { CapacitorConfig } from "@capacitor/cli";

// ponytail: server.url points at prod; no bundled web build, no live reload.
const config: CapacitorConfig = {
  appId: "app.shoulder.player",
  appName: "Shoulder",
  webDir: "www",
  server: {
    url: "https://shoulderapp.vercel.app",
    // Only the app and Supabase load inside the WebView. Google sign-in runs
    // in the system browser (apps/web/app/native-bridge.tsx), never here.
    allowNavigation: [
      "shoulderapp.vercel.app",
      "gzbwlancwxhtausyokxt.supabase.co",
    ],
  },
  android: {
    allowMixedContent: false,
  },
  plugins: {
    SplashScreen: {
      launchAutoHide: true,
      backgroundColor: "#faf9f7",
      androidSplashResourceName: "splash",
      splashFullScreen: true,
      splashImmersive: false,
    },
    StatusBar: {
      style: "DEFAULT",
      backgroundColor: "#faf9f7",
    },
  },
};

export default config;
