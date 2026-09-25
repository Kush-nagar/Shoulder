# Mobile app (Capacitor)

Block 09B, workstream W4. `apps/mobile` is a thin Capacitor 7 shell around the
production web app at `https://shoulder-demo.vercel.app`. There is no bundled
web build: `server.url` in `capacitor.config.ts` loads the live site directly,
so the app always shows what's deployed. `www/index.html` is only an offline
fallback the WebView shows if it can't reach the network.

## Architecture

- `capacitor.config.ts` — `appId: app.shoulder.player`, `server.url` pinned to
  the prod host, `allowNavigation` limited to that host, the Supabase project
  host (`gzbwlancwxhtausyokxt.supabase.co`, for auth callbacks/API calls), and
  `accounts.google.com` (Google OAuth redirect — see below).
- Plugins: `@capacitor/geolocation` (session tracking), `@capacitor/camera`,
  `@capacitor-community/keep-awake` (screen stays on during a live tracked
  session), `@capacitor/status-bar`, `@capacitor/splash-screen`,
  `@capacitor/app` (deep link handling), `@capacitor/browser` (system-browser
  OAuth, see below).
- `android/` — generated native project, buildable on Windows.
- `ios/` — generated native project; CocoaPods/xcodebuild steps need a Mac.
- No app code lives here. All product logic stays in `apps/web`; this package
  only wraps it and adds native permissions the WebView itself can't request.

## Build / run

Android debug APK (Windows, Mac, or Linux):

```
pnpm install
cd apps/mobile
npx cap sync android
cd android
./gradlew assembleDebug      # gradlew.bat on Windows
# output: android/app/build/outputs/apk/debug/app-debug.apk
```

Requires a JDK the Android Gradle Plugin accepts (**JDK 21**; this
environment only had JDK 17 on `JAVA_HOME`, so `assembleDebug` was not run
here — it failed at the toolchain-resolution step, not a code error) and
`ANDROID_HOME`/`sdk.dir` pointing at an Android SDK with platform 34/35 and
build-tools 34+. `apps/mobile/android/local.properties` is gitignored; each
machine sets `sdk.dir` itself.

iOS (Mac only, once a Mac is available):

```
cd apps/mobile
npx cap sync ios
npx cap open ios      # opens Xcode; pod install runs automatically via cap sync on a Mac
```

`ios/` was generated here (`npx cap add ios` works on Windows), but
`pod install` and `xcodebuild` need CocoaPods/Xcode, which don't run on
Windows. On a Mac: run `npx cap sync ios` (installs pods), open in Xcode, set
a signing team, and Build.

## Icons and splash

Generation via `@capacitor/assets` needs `sharp`'s native binary, which
failed to build in this sandbox (`node-gyp`/prebuilt binary mismatch — the
generic "sharp fails on Windows CI without a toolchain" failure). The
template Capacitor icon/splash placeholders currently ship as-is except the
adaptive-icon background color, which was set to the brand background
(`#faf9f7` in `android/app/src/main/res/values/ic_launcher_background.xml`)
by hand since that needs no image processing. To generate real icons/splash
from the brand mark once `sharp` installs cleanly (a Mac, Linux, or a
container with build tools, or `npm i sharp --platform=win32 --arch=x64`
forced from a working npm registry mirror):

```
cd apps/mobile
mkdir assets
# 1024x1024 icon source, 2732x2732 splash source, from apps/web/public/pwa-512.png
# upscaled/padded to size (see @capacitor/assets docs for exact filenames:
# icon-only.png, icon-foreground.png, icon-background.png, splash.png, splash-dark.png)
npx capacitor-assets generate
npx cap sync
```

## Google OAuth in the WebView

Google blocks OAuth from an embedded WebView user agent
(`Error 403: disallowed_useragent`) — Capacitor's WebView is treated as
embedded even though it loads a real site. Standard mitigation, implemented
here at the plugin/config level:

1. `@capacitor/browser` is installed so the app can open the Google OAuth URL
   in the system browser (Chrome Custom Tabs / `SFSafariViewController`)
   instead of the in-app WebView.
2. `allowNavigation` includes `accounts.google.com` so if a redirect briefly
   touches it inside the WebView (e.g. before a Browser.open call fires) it
   isn't silently blocked.

**A small web change is still needed and was intentionally not made here**
(W4 must not touch `apps/web`): when running inside Capacitor, the "Sign in
with Google" button must call `Browser.open({ url: googleOAuthUrl })` instead
of a plain `location.href` navigation, and the OAuth redirect must return to
either an HTTPS App Link (`https://shoulder-demo.vercel.app/auth/callback`,
already same-origin, works with no native change) or a custom scheme
(`app.shoulder.player://auth/callback`) that `@capacitor/app`'s
`appUrlOpen` listener hands back into the page. Given Supabase Auth already
redirects to an HTTPS callback URL on the deployed origin, the **simplest
fix requires zero native changes**: detect `window.Capacitor?.isNativePlatform()`
in `apps/web`'s Google sign-in handler and route through
`@capacitor/browser`'s `Browser.open()` (imported lazily so it's a no-op
bundle cost on the web) rather than a same-tab redirect, then close the
system browser tab (`Browser.close()`) once `appUrlOpen` fires for the
callback URL. This is a few lines in the existing sign-in button component;
it was left to a `apps/web`-owning workstream/coordinator to apply.

## Native permissions

- Android (`android/app/src/main/AndroidManifest.xml`):
  `ACCESS_FINE_LOCATION`, `ACCESS_COARSE_LOCATION`, `CAMERA`, optional camera
  feature (`android:required="false"`, so the app installs on devices
  without a camera).
- iOS (`ios/App/App/Info.plist`): `NSLocationWhenInUseUsageDescription`,
  `NSCameraUsageDescription` — both worded for what the feature is actually
  used for (session tracking, practice capture), per store review
  requirements.

## Store submission checklist

- [ ] Real app icon/splash generated from brand assets (see above).
- [ ] `appId` (`app.shoulder.player`) matches the registered bundle
      ID/package name in App Store Connect / Google Play Console.
- [ ] Privacy nutrition label / Data Safety form: location (used, not sold,
      linked to session tracking only), camera (used, not sold).
- [ ] Google OAuth web change above shipped, tested end-to-end on device.
- [ ] Privacy policy URL set (points at the same policy the web app links).
- [ ] Signed release build: Android keystore generated and stored outside
      the repo; iOS distribution certificate + provisioning profile in
      Xcode.
- [ ] `minSdkVersion`/target iOS version reviewed against current store
      minimums at submission time.
- [ ] Test the offline fallback page on airplane mode.
- [ ] Test camera/location permission prompts on first use, and denial
      handling (the web app must already degrade gracefully — no new native
      code changes that path).

### Apple guideline 4.2 (minimum functionality) risk

The app is a WebView wrapper of a web app, which 4.2 specifically flags for
rejection when a native shell adds nothing beyond "a website in a box."
Apple reviewers evaluate this at submission, not at build time, so this is a
real risk, not a checklist item that can be fully resolved in code. What
justifies native packaging here, to state explicitly in the review notes:

- **GPS session tracking** (distance, speed, sprints, heatmap) needs
  continuous, high-accuracy `Geolocation.watchPosition` and a wake lock
  during a live session — meaningfully more reliable in a native shell than
  a backgrounded mobile Safari tab.
- **Camera capture** for practice clips uses the native camera plugin
  rather than a browser file input, for a session that can run tens of
  minutes without the browser reclaiming the tab.
- The users are minors on a team roster; a installable, permission-scoped
  native app (rather than an always-open browser tab) is also the safer
  default for that use pattern.

If Apple still rejects on 4.2, the fallback is to not submit an iOS app at
all and rely on the installable PWA (`apps/web/app/manifest.ts`) for iOS
users, since Android (Play Store) has no equivalent minimum-functionality
gate for this shape of app.
