import type { CapacitorConfig } from "@capacitor/cli";

// ponytail: server.url points at prod; no bundled web build, no live reload.
const config: CapacitorConfig = {
  appId: "app.shoulder.player",
  appName: "Shoulder",
  webDir: "www",
  server: {
    url: "https://shoulder-demo.vercel.app",
    // Only these hosts may be navigated to from inside the WebView:
    // the app itself, Supabase (auth callbacks/API), and Google's
    // accounts domain for OAuth redirects that aren't blocked outright
    // (see docs/mobile.md for the "disallowed_useragent" issue).
    allowNavigation: [
      "shoulder-demo.vercel.app",
      "gzbwlancwxhtausyokxt.supabase.co",
      "accounts.google.com",
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
