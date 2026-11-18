import { useEffect, useState } from "react";
import { Eye, EyeOff, Twitch } from "lucide-react";
import { c } from "../theme.js";
import { cancelButton, fieldBox, headerButton, primaryButton, uiText } from "../styles.js";
import {
  cancelTwitchSignIn, errorText, getStream, getTwitch, saveStream, saveTwitchApp, setTwitchTitleNow, signOutTwitch, startTwitchSignIn,
} from "../api.js";
import { help, label12 } from "./streamStyles.js";

// Everything Twitch, in a browser window of its own (?view=twitch-settings; TwitchSettingsButton opens it), so it can be
// moved anywhere and left open: the stream key, the sign-in to Twitch that sets Stream control's title on Twitch
// (StreamControlTitle), and the Twitch extras (the title set from what's printing, chat commands, chat on the stream),
// which come in a later version and are shown greyed out until then. Save saves just
// these (changes on the Stream page not saved yet stay as they are) and tells the Stream page, wherever it's open, to
// show them.

export const WINDOW_PATH = "?view=twitch-settings"; // (relative: the plugin's own page, inside Farmhand or not)
const WINDOW_NAME = "farmhand-twitch-settings";
// the Stream page hears the window's saves on this (any tab or window of this Farmhand, in this browser)
export const STREAM_CHANNEL = "farmhand-twitch-plugin"; // (not the YouTube plugin's: each plugin hears only its own)
const announce = () => {
  try {
    const ch = new BroadcastChannel(STREAM_CHANNEL);
    ch.postMessage("saved");
    ch.close();
  } catch {
    // (an old browser: the Stream page catches up on its next look, within 5 seconds)
  }
};
// Open the window (or bring it forward if it's open already)
export const openTwitchSettings = () => {
  const w = window.open(WINDOW_PATH, WINDOW_NAME, "popup,width=640,height=720");
  w?.focus();
};

// The channel's pages on Twitch, from its name: [label, address, what it's for]
export const twitchLinks = (channel) => channel ? [
  ["Watch", `https://www.twitch.tv/${channel}`, "The channel as viewers see it"],
  ["Chat", `https://www.twitch.tv/popout/${channel}/chat?popout=`, "The channel's chat in a window of its own"],
  ["Stream Manager", `https://dashboard.twitch.tv/u/${channel}/stream-manager`, "Twitch's dashboard: chat, activity, title and category"],
  ["Analytics", `https://dashboard.twitch.tv/u/${channel}/analytics/channel-analytics`, "Viewers, followers and watch time"],
] : [];

// The extras to come: [key, name, what it will do]
const EXTRAS = [
  ["titleFromPrinting", "Stream title from what's printing", "Farmhand sets the Twitch title and category from the prints going on."],
  ["chatCommands", "Chat commands", "A bot answers viewers in chat, like !printers or !eta."],
  ["chatOnScreen", "Chat on the stream", "The latest Twitch chat shown over the picture."],
];

// The summary on the Stream page, and the button that opens the window
export function TwitchSettingsButton({ keySet, channel, onOpen }) {
  return (
    <div data-testid="stream-twitch-settings" style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
      <button type="button" data-testid="stream-twitch-settings-open" onClick={onOpen} style={headerButton()}>
        <Twitch size={14} /> Twitch settings
      </button>
      <span style={uiText(12, keySet ? c.textMuted : c.amber, { flex: 1, minWidth: 200 })}>
        {keySet ? "Stream key saved" : "No stream key yet: add it in Twitch settings to go live"}
        {channel ? ` · channel ${channel}` : " · no channel name (for the Watch and dashboard links)"}
      </span>
    </div>
  );
}

function Section({ title, children }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8, borderTop: `1px solid ${c.border}`, paddingTop: 12 }}>
      <div style={uiText(13, c.heading, { fontWeight: 600 })}>{title}</div>
      {children}
    </div>
  );
}

const field = { ...fieldBox(), padding: "6px 8px" };

// The window's page: reads the stream's settings (and again every 5 seconds; what's typed here isn't touched), and saves them.
export function TwitchSettingsWindow() {
  const [page, setPage] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState(null);
  const [savedAt, setSavedAt] = useState(null);

  useEffect(() => {
    document.title = "Twitch settings · Farmhand";
    let live = true;
    const look = (first) =>
      (first === true || !document.hidden) &&
      getStream().then((p) => live && (setPage(p), setLoadError(null))).catch((e) => live && setLoadError(errorText(e)));
    look(true);
    const timer = setInterval(look, 5000);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, []);

  // the page as the server answered, or null (the reason shown)
  const ask = async (call) => {
    setBusy(true);
    setProblem(null);
    try {
      const p = await call();
      setPage(p);
      announce();
      return p;
    } catch (e) {
      setProblem(errorText(e));
      return null;
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ minHeight: "100vh", background: c.bg, padding: "20px 16px" }}>
      <main style={{ maxWidth: 600, margin: "0 auto" }}>
        <div style={uiText(20, c.heading, { fontWeight: 700, display: "flex", alignItems: "center", gap: 8, marginBottom: 14 })}>
          <Twitch size={20} /> Twitch settings
        </div>
        {!page ? (
          <div style={uiText(13, loadError ? c.danger : c.textFaint)}>{loadError ? `Couldn't reach the plugin: ${loadError}` : "Loading…"}</div>
        ) : (
          <TwitchSettingsForm
            keySet={page.settings.keySet} twitch={page.settings.twitch} ready={page.settings.twitchReady} channel={page.settings.channel}
            live={page.status.live} busy={busy} problem={problem} savedAt={savedAt}
            onSave={async (fields) => {
              const p = await ask(() => saveStream(fields));
              if (p) setSavedAt(new Date());
              return p;
            }}
            onForgetKey={() => ask(() => saveStream({ clearKey: true }))}
          />
        )}
      </main>
    </div>
  );
}

// The settings themselves. `keySet`, `onForgetKey`; `channel`: the channel's name as saved; `twitch`: the extras as saved; `ready`: which can be
// turned on yet; `onSave(fields)`: saves just these, the page as the server answered or null; `problem`: what the
// server last refused; `savedAt`: when last saved.
function TwitchSettingsForm({ keySet, channel, twitch, ready, live, busy, problem, savedAt, onSave, onForgetKey }) {
  const [key, setKey] = useState("");
  const [name, setName] = useState(channel || "");
  const [showKey, setShowKey] = useState(false);
  const [extras, setExtras] = useState(() => ({ ...twitch }));
  const [saving, setSaving] = useState(false);
  const save = async () => {
    setSaving(true);
    const p = await onSave({ streamKey: key.trim(), channel: name.trim(), twitch: extras });
    setSaving(false);
    if (p) {
      setKey("");
      setName(p.settings.channel || "");
    }
  };

  return (
    <div style={{ background: c.panel, border: `1px solid ${c.border}`, borderRadius: 6, padding: 16 }}>
      <div data-testid="twitch-settings-window" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <Section title="Your Twitch channel">
          <input
            data-testid="twitch-channel" value={name} onChange={(e) => setName(e.target.value)} maxLength={200}
            placeholder="Its name, or its address: twitch.tv/yourname" style={field}
          />
          <div style={help}>
            The name in your channel's address. It gives the Stream page its links to watch the channel, its chat, Twitch's
            Stream Manager and Analytics. (The stream key doesn't say whose channel it is.)
          </div>
        </Section>

        <Section title="Stream key">
          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <input
              data-testid="twitch-stream-key" type={showKey ? "text" : "password"} autoComplete="new-password" value={key} onChange={(e) => setKey(e.target.value)}
              placeholder={keySet ? "Saved. Type a new one to replace it" : "Paste your Twitch stream key"} style={{ ...field, flex: 1, minWidth: 0 }}
            />
            <button type="button" onClick={() => setShowKey(!showKey)} aria-label={showKey ? "Hide" : "Show"} style={{ ...headerButton(), padding: "0 7px" }}>
              {showKey ? <EyeOff size={14} /> : <Eye size={14} />}
            </button>
            {keySet && (
              <button type="button" onClick={onForgetKey} disabled={busy} style={headerButton()}>
                Forget key
              </button>
            )}
          </div>
          <div style={help}>
            On Twitch, open Creator Dashboard → Settings → Stream, and Copy the Primary Stream key. It stays in the plugin: it
            isn't shown again. Keep it to yourself: anyone with it can stream on your channel.
            {live ? " A new key takes over straight away (the stream reconnects)." : ""}
          </div>
          <div style={help}>
            The stream's title, category and tags are set on Twitch itself, in Creator Dashboard → Stream Manager → Edit Stream
            Info. The title is Stream control's while it sends Twitch its layout, once you're signed in (below).
          </div>
        </Section>

        <StreamControlTitle />

        <Section title="Twitch extras">
          <div style={help}>Coming in a later version of the plugin: they're shown here so you know where they'll be.</div>
          {EXTRAS.map(([k, name, what]) => (
            <label key={k} style={{ ...label12, opacity: ready[k] ? 1 : 0.6 }} title={ready[k] ? undefined : "Coming in a later version"}>
              <input
                type="checkbox" data-testid={`twitch-${k}`} disabled={!ready[k]} checked={!!extras[k]}
                onChange={(e) => setExtras((x) => ({ ...x, [k]: e.target.checked }))}
              />
              {name} <span style={uiText(11, c.textFaint)}>({what})</span>
            </label>
          ))}
        </Section>
      </div>
      <div
        style={{
          position: "sticky", bottom: 0, background: c.panel, display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 8,
          borderTop: `1px solid ${c.border}`, padding: "12px 0 0", marginTop: 12, flexWrap: "wrap",
        }}
      >
        <span style={uiText(12, problem ? c.danger : c.green, { flex: 1, minWidth: 200, lineHeight: 1.5 })}>
          {problem || (savedAt ? `Saved at ${savedAt.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}.` : "")}
        </span>
        <button type="button" onClick={() => window.close()} disabled={saving} style={cancelButton(saving)}>Close window</button>
        <button type="button" data-testid="twitch-save" onClick={save} disabled={saving} style={primaryButton(saving)}>
          {saving ? "Saving…" : "Save"}
        </button>
      </div>
    </div>
  );
}

const when = (d) => d ? d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "";

// The stream's title on Twitch, kept to Stream control's: the Twitch application the plugin signs in through, the
// sign-in itself (a code typed on twitch.tv/activate), and the title last set. Its buttons act at once (no Save).
function StreamControlTitle() {
  const [tw, setTw] = useState(null);
  const [problem, setProblem] = useState(null);
  const [busy, setBusy] = useState(false);
  const [clientId, setClientId] = useState(null); // (null: as saved)
  const [secret, setSecret] = useState("");

  useEffect(() => {
    let on = true;
    const look = () => getTwitch().then((t) => on && setTw(t)).catch((e) => on && setProblem(errorText(e)));
    look();
    const timer = setInterval(look, tw?.signingIn ? 2000 : 5000);
    return () => {
      on = false;
      clearInterval(timer);
    };
  }, [!!tw?.signingIn]);

  const act = async (call) => {
    setBusy(true);
    setProblem(null);
    try {
      setTw(await call());
      return true;
    } catch (e) {
      setProblem(errorText(e));
      return false;
    } finally {
      setBusy(false);
    }
  };
  const saveApp = async () => {
    if (await act(() => saveTwitchApp({ clientId: (clientId ?? tw.clientId).trim(), clientSecret: secret.trim() }))) {
      setClientId(null);
      setSecret("");
    }
  };

  const title = "Stream title from Stream control";
  if (!tw) return <Section title={title}><div style={help}>{problem || "Loading…"}</div></Section>;
  const appChanged = (clientId !== null && clientId.trim() !== tw.clientId) || secret.trim();
  return (
    <Section title={title}>
      <div style={help}>
        While Farmhand's Stream control sends Twitch its layout, the title written in Stream control is the Twitch stream's
        title: it's set on Twitch, and set again within seconds whenever it's changed in Stream control. That takes
        signing in to Twitch, once.
      </div>
      {tw.signedInAs ? (
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span data-testid="twitch-signed-in" style={uiText(12, c.green, { flex: 1 })}>Signed in to Twitch as {tw.signedInAs}</span>
          <button type="button" onClick={() => act(setTwitchTitleNow)} disabled={busy} style={headerButton()}>Set title now</button>
          <button type="button" onClick={() => act(signOutTwitch)} disabled={busy} style={headerButton()}>Sign out</button>
        </div>
      ) : tw.signingIn ? (
        <div data-testid="twitch-signing-in" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <div style={uiText(13, c.text, { lineHeight: 1.5 })}>
            On Twitch, signed in as your channel, open{" "}
            <a href={tw.signingIn.url} target="_blank" rel="noreferrer" style={{ color: c.amber }}>{tw.signingIn.url.replace(/^https?:\/\//, "")}</a>{" "}
            and type this code:
          </div>
          <div style={uiText(24, c.heading, { fontWeight: 700, letterSpacing: 2 })}>{tw.signingIn.code}</div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <span style={uiText(12, c.textMuted, { flex: 1 })}>Waiting for Twitch… the code works until {when(tw.signingIn.expiresAt)}.</span>
            <button type="button" onClick={() => act(cancelTwitchSignIn)} disabled={busy} style={headerButton()}>Cancel</button>
          </div>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "6px 8px", alignItems: "center" }}>
            <span style={uiText(12, c.textMuted)}>Client ID</span>
            <input data-testid="twitch-client-id" value={clientId ?? tw.clientId} onChange={(e) => setClientId(e.target.value)} maxLength={100} style={field} placeholder="From your application on dev.twitch.tv" />
            <span style={uiText(12, c.textMuted)}>Client Secret</span>
            <input
              data-testid="twitch-client-secret" type="password" autoComplete="new-password" value={secret} onChange={(e) => setSecret(e.target.value)}
              maxLength={100} style={field} placeholder={tw.secretSet ? "Saved. Type a new one to replace it" : "Optional, but keeps you signed in"}
            />
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "flex-end" }}>
            {appChanged && <button type="button" onClick={saveApp} disabled={busy} style={headerButton()}>Save application</button>}
            <button type="button" data-testid="twitch-sign-in" onClick={() => act(startTwitchSignIn)} disabled={busy || !tw.clientId || appChanged} style={primaryButton(busy || !tw.clientId || appChanged)}>
              Sign in to Twitch
            </button>
          </div>
          <div style={help}>
            Signing in goes through an application of your own (once): on dev.twitch.tv, open Your Console → Applications →
            Register Your Application. Name it (say “Farmhand title”), put http://localhost as its OAuth Redirect URL, pick
            any category, and Client Type Confidential. Copy its Client ID here, and with New Secret its Client Secret, and
            Save application. Then Sign in to Twitch: a code shows here to type on Twitch. (Without a Client Secret it still
            works, but Twitch may ask you to sign in again after 30 days.)
          </div>
          {tw.signInError && <div style={uiText(12, c.danger, { lineHeight: 1.5 })}>{tw.signInError}</div>}
        </div>
      )}
      {tw.title.title && (
        <div data-testid="twitch-title-now" style={uiText(12, c.textMuted, { lineHeight: 1.5 })}>
          Title on Twitch: <b style={{ color: c.text }}>{tw.title.title}</b> (set at {when(tw.title.at)})
        </div>
      )}
      {tw.title.error && tw.signedInAs && <div style={uiText(12, c.danger, { lineHeight: 1.5 })}>{tw.title.error}</div>}
      {problem && <div style={uiText(12, c.danger, { lineHeight: 1.5 })}>{problem}</div>}
    </Section>
  );
}
