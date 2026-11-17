import { c } from "./theme.js";
import { panelBox, uiText } from "./styles.js";
import { ClipsPanel } from "./ClipsPanel.jsx";

// What the plugin adds to the Stream page, under the live panel: where the stream goes while being tried out, each
// camera live or down while live, when Farmhand isn't answering (the stream carries on without it), and clips.
const timeOf = (iso) => (iso ? new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "");

export function PluginPanel({ page, farmhandError }) {
  const status = page.status;
  const down = status.cameraStates.filter((x) => x.state === "down");
  const slow = status.cameraStates.filter((x) => x.state === "live" && x.slow);
  return (
    <>
      {page.testDestination && (
        <div data-testid="stream-test-destination" style={uiText(12, c.amber, { lineHeight: 1.5 })}>
          Being tried out: the stream goes to {page.testDestination}/&lt;stream key&gt;, never to Twitch.
        </div>
      )}
      {status.live && status.cameraStates.length > 0 && (
        <div data-testid="stream-camera-states" style={panelBox({ padding: "10px 14px", display: "flex", flexDirection: "column", gap: 4 })}>
          <div style={uiText(12, c.textMuted)}>
            {down.length ? `${down.length} camera${down.length === 1 ? " is" : "s are"} down: ${down.length === 1 ? "its square says" : "their squares say"} “Camera down” until they're back.` : "Every camera is live."}
          </div>
          {slow.length > 0 && (
            <div data-testid="stream-camera-slow" style={uiText(12, c.amber, { lineHeight: 1.5 })}>
              {slow.length === 1 ? "A camera sends" : `${slow.length} cameras send`} fewer than 15 new pictures a second, so{" "}
              {slow.length === 1 ? "its square moves" : "their squares move"} less smoothly than the stream. Set the camera (or go2rtc on its
              printer) to send at least 15 frames a second at this size.
            </div>
          )}
          {status.cameraStates.map((x) => (
            <div key={x.key} data-testid="stream-camera-state" style={uiText(12, x.state === "down" ? c.danger : x.state === "live" ? (x.slow ? c.amber : c.green) : c.textFaint)}>
              {x.label}: {x.state === "down" ? `down${x.since ? ` since ${timeOf(x.since)}` : ""}${x.said ? ` (${x.said})` : ""}` : x.state === "live" ? `live${x.fps != null ? `, ${Math.round(x.fps)} fps` : ""}${x.slow ? " (under 15)" : ""}` : "connecting…"}
            </div>
          ))}
        </div>
      )}
      {(status.farmhand || farmhandError) && (
        <div data-testid="stream-farmhand" style={uiText(12, c.amber, { lineHeight: 1.5 })}>
          Farmhand isn't answering ({status.farmhand || farmhandError}). The stream carries on: cameras are read at the addresses last
          heard of, and the words under them are just the printers' names until Farmhand is back.
        </div>
      )}
      <ClipsPanel />
    </>
  );
}
