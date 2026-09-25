"use client";

import { useEffect } from "react";

// Capacitor injects this bridge into the page when the site runs inside the
// Shoulder app (apps/mobile); plugins resolve at runtime, so the web bundle
// needs no Capacitor dependency. On the plain web this component does nothing.
type Listener = { remove(): void };
type Bridge = {
  isNativePlatform(): boolean;
  Plugins: {
    Browser: {
      open(o: { url: string }): Promise<void>;
      close(): Promise<void>;
    };
    App: {
      addListener(
        event: "appUrlOpen",
        handler: (event: { url: string }) => void,
      ): Promise<Listener>;
    };
  };
};

const CALLBACK = "app.shoulder.player://auth/callback";

export function NativeBridge() {
  useEffect(() => {
    const cap = (window as { Capacitor?: Bridge }).Capacitor;
    if (!cap?.isNativePlatform()) return;

    // Google refuses embedded WebViews: start the PKCE flow here (the verifier
    // cookie stays in this WebView) and show only Google in the system browser.
    const onSubmit = async (event: SubmitEvent) => {
      const form = event.target as HTMLFormElement;
      if (new URL(form.action).pathname !== "/auth/google") return;
      event.preventDefault();
      const body = new FormData(form);
      body.set("native", "1");
      const reply = await fetch("/auth/google", { method: "POST", body });
      const data = (await reply.json().catch(() => null)) as {
        url?: string;
      } | null;
      if (data?.url) await cap.Plugins.Browser.open({ url: data.url });
      else window.location.assign("/auth/sign-in?error=1");
    };
    document.addEventListener("submit", onSubmit);

    // Google returns through the app scheme; finish on our own callback, where
    // the verifier lives, so a code intercepted elsewhere is useless.
    const listener = cap.Plugins.App.addListener("appUrlOpen", ({ url }) => {
      if (!url.startsWith(CALLBACK)) return;
      void cap.Plugins.Browser.close().catch(() => undefined);
      window.location.assign(`/auth/callback${new URL(url).search}`);
    });

    return () => {
      document.removeEventListener("submit", onSubmit);
      void listener.then((l) => l.remove());
    };
  }, []);
  return null;
}
