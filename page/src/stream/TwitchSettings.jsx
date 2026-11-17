import { useEffect, useState } from "react";
import { Eye, EyeOff, Twitch } from "lucide-react";
import { c } from "../theme.js";
import { cancelButton, fieldBox, headerButton, primaryButton, uiText } from "../styles.js";
import { errorText, getStream, saveStream } from "../api.js";
import { help, label12 } from "./streamStyles.js";

// Everything Twitch, in a browser window of its own (?view=twitch-settings; TwitchSettingsButton opens it), so it can be
// moved anywhere and left open: the stream key, and the Twitch extras (the title set from what's printing, chat
// commands, chat on the stream), which come in a later version and are shown greyed out until then. Save saves just
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
            keySet={page.settings.keySet} twitch={page.settings.twitch} extrasReady={page.settings.twitchExtrasReady} channel={page.settings.channel}
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

// The settings themselves. `keySet`, `onForgetKey`; `channel`: the channel's name as saved; `twitch`: the extras as saved; `extrasReady`: whether they can be
// turned on yet; `onSave(fields)`: saves just these, the page as the server answered or null; `problem`: what the
// server last refused; `savedAt`: when last saved.
function TwitchSettingsForm({ keySet, channel, twitch, extrasReady, live, busy, problem, savedAt, onSave, onForgetKey }) {
  const [key, setKey] = useState("");
  const [name, setName] = useState(channel || "");
  const [showKey, setShowKey] = useState(false);
  const [extras, setExtras] = useState(() => ({ ...twitch }));
  const [saving, setSaving] = useState(false);
  const save = async () => {
    setSaving(true);
    const p = await onSave({ streamKey: key.trim(), channel: name.trim(), twitch: extrasReady ? extras : undefined });
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
            Info, until the title from what's printing comes in a later version.
          </div>
        </Section>

        <Section title="Twitch extras">
          {!extrasReady && <div style={help}>Coming in a later version of the plugin: they're shown here so you know where they'll be.</div>}
          {EXTRAS.map(([k, name, what]) => (
            <label key={k} style={{ ...label12, opacity: extrasReady ? 1 : 0.6 }} title={extrasReady ? undefined : "Coming in a later version"}>
              <input
                type="checkbox" data-testid={`twitch-${k}`} disabled={!extrasReady} checked={!!extras[k]}
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
