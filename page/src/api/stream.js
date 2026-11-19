// The Stream page: printers' cameras sent live to Twitch by the plugin itself, laid out in a grid of squares. The
// stream key is sent once and never comes back: the page only learns whether it's there.
import { API_BASE, del, jsonBody, post, request } from "./client.js";

// { settings: { destination, cols, rows, cells: [per square, row by row: { camera: "printer id:camera name" } | a card
// { background, image, slideshow, seconds, text, color, picture_box: { x, y, w, h }, text_box: { x, y, size } (parts of the square) }; a camera may have its own background too | null], cameras (the cameras in square order), showStatus, layout: "grid" | "cycle", resolution,
// secondsAll, secondsEach, borderColor: "#RRGGBB", background (the stream's colour), font and color (its words'), music (the stream folder's music
// played, or a silent sound track), musicVolume (0 to 100), musicShuffle, keySet, twitch (the Twitch extras), twitchExtrasReady },
// status: { live, onAir, startedAt, destination, cameras: [labels], error }, destinations: [{ key, label }],
// resolutions: [{ key: "720p" | "1080p", label }], fonts: [{ key, label, generic }] (what a square's words can be written in),
// media: { path, windows_path (the stream folder as Windows reaches it over the network, or null), images: [file names], slideshows: [{ name, images: [file names] }], music: [MP3s' file names], error } (the stream folder) }
const normalizeStream = (s) => ({
  settings: {
    destination: s.settings.destination,
    cols: s.settings.cols,
    rows: s.settings.rows,
    cells: s.settings.cells,
    cameras: s.settings.cameras,
    showStatus: s.settings.show_status,
    layout: s.settings.layout,
    resolution: s.settings.resolution,
    secondsAll: s.settings.seconds_all,
    secondsEach: s.settings.seconds_each,
    borderColor: s.settings.border_color,
    background: s.settings.background,
    font: s.settings.font, // the stream's words: every square's and camera's unless it has its own
    color: s.settings.color,
    music: !!s.settings.music,
    musicVolume: s.settings.music_volume ?? 50,
    musicShuffle: s.settings.music_shuffle !== false,
    delay: s.settings.delay ?? 60, // seconds the stream is held before Twitch gets it (0 to 120)
    // the holding screen, shown after the plugin's own restart while the delay fills again: { text, image, background,
    // color, font } (null colours and font: the stream's own)
    holding: { text: "Back in a minute", image: null, background: null, color: null, font: null, ...(s.settings.holding || {}) },
    // the Twitch extras (the Twitch settings window), coming in a later version: titleFromPrinting, chatCommands,
    // chatOnScreen; and whether they can be turned on yet: all of them (twitchExtrasReady), each one (twitchReady)
    twitch: ((t) => ({
      titleFromPrinting: !!t.title_from_printing, chatCommands: !!t.chat_commands, chatOnScreen: !!t.chat_on_screen,
    }))(s.settings.twitch || {}),
    twitchExtrasReady: !!s.settings.twitch_extras_ready,
    twitchReady: ((r) => ({
      titleFromPrinting: !!r.title_from_printing, chatCommands: !!r.chat_commands, chatOnScreen: !!r.chat_on_screen,
    }))(s.settings.twitch_ready || {}),
    // the Twitch channel's name (twitch.tv/<name>), for the Watch, Chat, Stream Manager and Analytics links; null: none set
    channel: s.settings.channel || null,
    keySet: s.settings.key_set,
    enabled: s.settings.enabled !== false, // the page's switch: off, nothing streams and the page rests
  },
  status: {
    live: s.status.live,
    onAir: s.status.on_air,
    startedAt: s.status.started_at,
    destination: s.status.destination,
    cameras: s.status.cameras,
    error: s.status.error,
    encoder: s.status.encoder || null,
    // where the cameras are unpacked and fitted, while live: "gpu" (the NVIDIA card) or "cpu"; and why not the card
    // (it was tried and didn't work), or null
    cameraDecoding: s.status.camera_decoding || null,
    cameraDecodingNote: s.status.camera_decoding_note || null,
    // the size going out, set when it went live (a new one saved while live waits for the next Go live); null otherwise
    resolution: s.status.resolution || null,
    // what the self-check last did this time live (next to no video reaching Twitch): { at, message }, or null
    selfCheck: s.status.self_check || null, // "nvenc" (an NVIDIA card compresses it) or "cpu", while live
    // each camera while live, in square order: { key, label, state: "live" | "down" | "starting", since, said }
    cameraStates: s.status.camera_states || [],
    // Farmhand didn't answer at the last Go live (its cameras were read at the addresses last heard of): why, or null
    farmhand: s.status.farmhand || null,
    // how long the picture going out has run (s), and when that was heard: the preview counts from the same start
    runningFor: typeof s.status.running_for === "number" ? s.status.running_for : null,
    // the server's time of day (s): slideshows and taking turns count from it, on the stream and in the preview
    serverTime: typeof s.status.server_time === "number" ? s.status.server_time : null,
    heardAt: Date.now(),
    // the music going out, while live: { on, playing, track (its file name, null before the first), at (s into it) }
    music: s.status.music || null,
    // the delay before Twitch, while live: { seconds, held (seconds held now), filling (nothing sent to Twitch yet) }
    delay: s.status.delay || null,
    holding: !!s.status.holding, // the holding screen is going out (after the plugin's own restart, while the delay fills)
    // a new layout is on its way (waiting a moment for more changes, then warming up beside the one going out)
    changing: !!s.status.changing,
  },
  // Farmhand's Stream control: while following, its layout is sent (not this page's) and the layout editor gives way to
  // "Controlled by Stream control". { following, revision, savedAt, title, error }
  streamControl: {
    following: !!s.stream_control?.following,
    revision: s.stream_control?.revision ?? null,
    savedAt: s.stream_control?.saved_at || null,
    title: s.stream_control?.title || null,
    error: s.stream_control?.error || null,
    copying: s.stream_control?.copying || null, // how far copying its pictures and music has got, while it is
  },
  // being tried out: the rtmp:// address the stream goes to instead of Twitch, or null
  testDestination: s.test_destination || null,
  destinations: s.destinations,
  resolutions: s.resolutions,
  fonts: s.fonts || [],
  media: { ...s.media, music: s.media.music || [] },
});

export const getStream = async () => normalizeStream(await request("/stream"));

// Save what's given: { destination, cols, rows, cells (the three together), showStatus, layout, resolution, secondsAll,
// secondsEach, borderColor, background, font, color, music, musicVolume, musicShuffle, streamKey (blank: keep the saved one),
// clearKey, enabled (the page's switch: false stops the stream), twitch (the extras), channel (a name or address; "": none) }. While live, a new picture starts the stream again.
export const saveStream = async (s = {}) =>
  normalizeStream(
    await request(
      "/stream",
      jsonBody("PUT", {
        destination: s.destination, cols: s.cols, rows: s.rows, cells: s.cells, show_status: s.showStatus, layout: s.layout,
        resolution: s.resolution, seconds_all: s.secondsAll, seconds_each: s.secondsEach, border_color: s.borderColor, background: s.background, font: s.font, color: s.color,
        music: s.music, music_volume: s.musicVolume, music_shuffle: s.musicShuffle, delay: s.delay,
        stream_key: s.streamKey || null, clear_key: !!s.clearKey, enabled: s.enabled, holding: s.holding, channel: s.channel,
        twitch: s.twitch ? {
          title_from_printing: s.twitch.titleFromPrinting, chat_commands: s.twitch.chatCommands, chat_on_screen: s.twitch.chatOnScreen,
        } : undefined,
      }),
    ),
  );

export const startStream = async () => normalizeStream(await post("/stream/start"));

// Signing in to Twitch, so Stream control's title is set on Twitch: { clientId, secretSet, signedInAs (the channel's
// login, or null), signingIn: { code, url, expiresAt } | null (the code to type on Twitch), signInError,
// title: { title (last set on Twitch), at (Date), error } }. The Client Secret and the sign-in never come back.
const normalizeTwitch = (t) => ({
  clientId: t.client_id || "", secretSet: !!t.secret_set, signedInAs: t.signed_in_as || null,
  signingIn: t.signing_in ? { code: t.signing_in.code, url: t.signing_in.url, expiresAt: new Date(t.signing_in.expires_at * 1000) } : null,
  signInError: t.sign_in_error || null,
  title: { title: t.title?.title || null, at: t.title?.at ? new Date(t.title.at * 1000) : null, error: t.title?.error || null },
});
export const getTwitch = async () => normalizeTwitch(await request("/stream/twitch"));
// { clientId ("": forget it, and the sign-in), clientSecret (blank: keep the saved one), clearSecret }
export const saveTwitchApp = async (a = {}) =>
  normalizeTwitch(await request("/stream/twitch/app", jsonBody("PUT", { client_id: a.clientId, client_secret: a.clientSecret || null, clear_secret: !!a.clearSecret })));
export const startTwitchSignIn = async () => normalizeTwitch(await post("/stream/twitch/sign-in"));
export const cancelTwitchSignIn = async () => normalizeTwitch(await post("/stream/twitch/sign-in/cancel"));
export const signOutTwitch = async () => normalizeTwitch(await post("/stream/twitch/sign-out"));
export const setTwitchTitleNow = async () => normalizeTwitch(await post("/stream/twitch/title"));
export const stopStream = async () => normalizeStream(await post("/stream/stop"));

// The stream folder's pictures, as files: single pictures in images/, each slideshow a folder in slideshows/ (PNG, JPEG,
// WebP or SVG; uploads under 10 MB). Files dropped into the folder by hand count too.
const enc = encodeURIComponent;
const filesBody = (files) => {
  const form = new FormData();
  for (const file of files) form.append("files", file);
  return { method: "POST", body: form };
};
// a font a square's words can be written in, as the server has it (for the page to show them as the stream does)
export const streamFontUrl = (key) => `${API_BASE}/stream/fonts/${enc(key)}`;
export const streamPictureUrl = (name) => `${API_BASE}/stream/pictures/${enc(name)}`;
export const slideshowPictureUrl = (show, name) => `${API_BASE}/stream/slideshows/${enc(show)}/pictures/${enc(name)}`;
// read the stream folder again (pictures copied in or taken out by hand): the server doesn't keep looking at it
export const scanStreamFolder = async () => normalizeStream(await post("/stream/scan"));
export const uploadStreamPictures = async (files) => normalizeStream(await request("/stream/pictures", filesBody(files)));
export const removeStreamPicture = async (name) => normalizeStream(await del(`/stream/pictures/${enc(name)}`));
export const createSlideshow = async (name) => normalizeStream(await request("/stream/slideshows", jsonBody("POST", { name })));
// a slideshow's new name: its folder is renamed, and every square showing it (on the page and in saved layouts) follows
export const renameSlideshow = async (show, name) => normalizeStream(await request(`/stream/slideshows/${enc(show)}`, jsonBody("PUT", { name })));
export const removeSlideshow = async (name) => normalizeStream(await del(`/stream/slideshows/${enc(name)}`));
export const uploadSlideshowPictures = async (show, files) => normalizeStream(await request(`/stream/slideshows/${enc(show)}/pictures`, filesBody(files)));
// a blank screen at the end of a slideshow: its colour and the words written on it (deleted as a picture is)
export const addSlideshowBlank = async (show) => normalizeStream(await post(`/stream/slideshows/${enc(show)}/blanks`));
// a slideshow's pictures in the order chosen (kept in its folder)
export const orderSlideshow = async (show, order) => normalizeStream(await request(`/stream/slideshows/${enc(show)}/order`, jsonBody("PUT", { order })));
export const removeSlideshowPicture = async (show, name) => normalizeStream(await del(`/stream/slideshows/${enc(show)}/pictures/${enc(name)}`));

// The stream's music: MP3s in the stream folder's music folder (uploads under 50 MB), played one after another, round
// and round, starting with the stream. Tracks added while live join its next round.
// While live: "play", "pause", "next" or "back" (the track from its start, or in its first 3 s the one before).
export const musicControl = async (action) => normalizeStream(await post(`/stream/music/${action}`));
export const streamTrackUrl = (name) => `${API_BASE}/stream/music/${enc(name)}`;
// The volume slider while live: the music going out follows it straight away, not saved. null: back to the saved volume.
// Said again every few seconds while it stays (a volume not said for 20 s goes back by itself). `leaving`: the page is
// closing, so it's sent in a way that still arrives (sendBeacon).
export const tryMusicVolume = (volume, leaving = false) => {
  const body = JSON.stringify({ volume });
  if (leaving && navigator.sendBeacon) return navigator.sendBeacon(`${API_BASE}/stream/music-volume`, new Blob([body], { type: "application/json" }));
  return request("/stream/music-volume", { method: "POST", headers: { "Content-Type": "application/json" }, body }).catch(() => null);
};
export const uploadStreamMusic = async (files) => normalizeStream(await request("/stream/music", filesBody(files)));
export const removeStreamTrack = async (name) => normalizeStream(await del(`/stream/music/${enc(name)}`));

