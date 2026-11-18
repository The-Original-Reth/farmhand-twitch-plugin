# FarmHand - Twitch Plugin

The farm's live stream to **Twitch**, as a plugin for [Farmhand](https://github.com/The-Original-Reth/farmhand), in its
own repository and its own Docker container, talking to Farmhand only through Farmhand's plugin API.

**Installing it:** [INSTALL.md](INSTALL.md) takes you from a machine with Docker to going live, step by step: the NAS
folders, the compose file, adding it on Farmhand's Plugins page and where its token comes from.

The Twitch Stream plugin (id `twitch`) sends printers' cameras live to Twitch, no OBS needed, from a container of its
own, so a Farmhand update, restart or crash never stops the stream. It began as a copy of the
[YouTube plugin](https://github.com/The-Original-Reth/farmhand-youtube-plugin) and works the same way: the grid of
squares, cards with pictures, slideshows and words, the music, the words under the cameras, taking turns, the
resolution, the delay, saved layouts and clips.

**It's independent of the YouTube plugin.** Each reads the printers' cameras itself (the cameras' go2rtc or MJPEG
streamer hands every reader the same copy, so a second plugin costs a printer's Pi next to nothing), and each has its
own layout, cameras, pictures, music, saved layouts and clips. Both can run on the same machine (Twitch on port 8081,
YouTube on 8080) and stream at the same time: they use different keys on different sites. The page's browser storage
(Mute, the cameras last seen) is its own too, though both pages are shown at Farmhand's address.

Once it's added, **Twitch** is in Farmhand's menu and opens the plugin's page inside Farmhand (`/plugin/twitch`), in
Farmhand's colours.

What it does:

- **Each camera is read on its own.** A camera that stops shows **Camera down** with the printer's name, and goes back
  to live video by itself; the other cameras and the connection to Twitch carry on.
- **Cameras at different frame rates** all play at the stream's 15 a second; a slow camera just changes less often in
  its square. The page shows each live camera's frame rate and warns about one under 14 a second.
- **It goes live again by itself** after its own restart (a reboot, a power cut, a new image), if it was live. While its
  delay fills again, Twitch is shown a **holding screen** (its words, picture, colours and font are set on the page), so
  the channel stays live; then it switches to the cameras with the whole delay in place.
- **It mends itself.** When next to nothing reaches Twitch for a minute, it starts the picture again (and, if that
  doesn't help, the connection to Twitch). A stall that long has used the delay up, so the holding screen goes out
  again for about a minute while the delay fills. A shorter stall uses up part of the delay, which doesn't come back by
  itself: once it's been 10 s or more short for a minute, the holding screen goes out for about the seconds missing
  while they're collected again (at most once every 10 minutes), and the page says so.
- **Farmhand going down doesn't stop it.** The cameras are read at the addresses last heard of, and the words under
  them become just the printers' names until Farmhand is back.
- **It reads only what it needs**: the cameras' addresses (`cameras:read`) and what each printer is printing
  (`prints:read`). Its settings, Twitch stream key and saved layouts are in its own volume (`/data/settings.json`,
  readable only by the plugin), and its API never answers the key.
- **Farmhand's Stream control** (Farmhand's built-in plugin for designing one stream and sending it everywhere): tick
  Twitch under its Streams and **Stream control's layout takes over**. The plugin sends Farmhand's design (the grid, its
  squares, the music, the holding screen) in place of its own layout, which it keeps as it is and goes back to
  as soon as Stream control is switched off or Twitch is unticked. Its page then shows only **Controlled by Stream control**
  (it all comes back when Stream control lets go); the stream key, the channel and the Twitch settings stay the plugin's,
  in its Twitch settings window, which Stream control opens from Farmhand (`?view=twitch-settings`). Farmhand's **Go live** and
  **Stop** start and stop it (`/api/stream-control`, `stream:read`). Changes saved in Stream control reach the stream
  within a few seconds, as a change saved here does.
- **Clips**: **Save clip** saves the last 1 second to 5 minutes of what went to Twitch as an MP4 in the NAS's Twitch
  clips folder (see [Clips](#clips)).

**Twitch settings** (a window of its own, opened from the page) hold the stream key and your **channel's name**. The
name gives the live panel its links, as the YouTube plugin has Watch and YouTube Studio: **Watch** (the channel),
**Chat** (its chat in a window of its own), **Stream Manager** (Twitch's dashboard) and **Analytics**. The stream key
doesn't say whose channel it is, so the name is asked for. The stream's category and tags are set on Twitch itself
(Creator Dashboard → Stream Manager → Edit Stream Info).

**The stream's title is Stream control's**: while Farmhand's Stream control sends Twitch its layout, the title written in
Stream control is set as the Twitch stream's title, and set again within seconds whenever it's changed there (it's
looked at every 10 seconds and sent only when it changed). With Stream control off, or Twitch unticked in it, the title
is left as it is on Twitch.

Changing the title takes Twitch's own API, so the plugin signs in to Twitch as your channel, once (Twitch settings →
Stream title from Stream control):

1. On [dev.twitch.tv](https://dev.twitch.tv/console/apps), Register Your Application: any name, OAuth Redirect URL
   `http://localhost` (not used), any category, Client Type **Confidential**.
2. In Twitch settings, paste its **Client ID** and (with New Secret) its **Client Secret**, and Save application. Without a
   secret it works too, but Twitch may ask you to sign in again after 30 days.
3. **Sign in to Twitch**: a code shows; type it on [twitch.tv/activate](https://www.twitch.tv/activate) as your channel.

It's Twitch's device sign-in, so nothing has to reach the plugin from outside. The secret and the sign-in stay in the
plugin's settings file and are never shown again; the sign-in is checked with Twitch every hour. Three Twitch extras
have their place in the settings already, greyed out until they're built: the **stream title from what's printing**,
**chat commands** (a bot answering `!printers`, `!eta`…) and **chat on the stream**.

The stream goes to Twitch's global ingest over RTMPS (`rtmps://ingest.global-contribute.live-video.net:443/app/`), which
picks the nearest Twitch server, at 720p (2500 kbit/s) or 1080p (3500 kbit/s), 15 frames a second, a keyframe every 2
seconds, with AAC sound.

| Path | What it is |
|---|---|
| `farmhand-plugin.json` | The manifest: id `twitch`, port 8080 in the container, a page in Farmhand's menu, its permissions |
| `streamer/live_stream/` | The engine; `constants.py` says where the stream goes, `twitch_choices.py` keeps the Twitch extras, `feeders.py` reads each camera |
| `streamer/stream_media.py`, `routes.py` | The stream folder and the page's API |
| `streamer/store.py`, `farm.py`, `layouts.py`, `app.py` | The plugin's own: its settings file, reading Farmhand, saved layouts, the web server |
| `streamer/live_stream/clips.py`, `streamer/clip_routes.py` | Clips: what went to Twitch kept five minutes, and saved as MP4s |
| `page/` | The page, a small Vite build of its own (`npm run build` puts it in `streamer/web/`); `src/stream/TwitchSettings.jsx` the Twitch settings window |
| `tests/` | Tests against stand-ins for Farmhand's plugin API and ffmpeg (`python -m pytest -q`) |

## Build it

On the machine that will run it (Docker installed), from a copy of this repository:

```bash
git clone https://github.com/The-Original-Reth/farmhand-twitch-plugin.git && cd farmhand-twitch-plugin
docker build -t farmhand-twitch .
```

## Where it saves

Like Farmhand, the plugin keeps everything in one **save location** on the NAS, set on its settings (Farmhand's
**Settings** page, under its name): the share's address as `\\server\share\folder` with its login. The plugin mounts it
itself (its container has `SYS_ADMIN` and `DAC_READ_SEARCH` for that, as Farmhand's has) and uses a folder inside it
for each thing it keeps, made if it isn't there:

- **Stream folder** (`Twitch stream`): the stream's pictures (`images/`), slideshows (`slideshows/<name>/`) and music
  (`music/`). Pictures can be PNG, JPEG, WebP or SVG. It isn't the YouTube plugin's `stream` folder, so the two streams
  never share pictures or music by accident; choose the same folder with **Change…** if you want them to.
- **Twitch clips** (`Twitch clips`): where **Save clip** puts its MP4s.

Each is shown as people reach it on the network, with a **Change…** to put it in another folder of the save location.
The password is kept in the plugin's own volume and never comes back out. Until a save location is set, the plugin uses
the folders its container is given, `/media` and `/clips` (`./media` and `./clips` beside its compose file).

## Clips

The **Clip** drop-down on the page says what to clip: **Stream**, or any camera Farmhand can see.

- **Stream:** **Save clip** saves the last stretch of what went to Twitch, at once: from 1 second to 5 minutes (3
  seconds unless changed), copied as it is with no compressing again. It starts on the whole frame at or just before
  the time asked for (one comes every 2 seconds), so a clip can be up to 2 seconds longer than asked.
- **A camera:** **Record clip** records the next stretch from that camera, straight from it, in the background.

Clips are named for when they were taken, e.g. `2026-11-12 18-26-03 (30 s).mp4`, and the page lists the newest ten.

## Run it

The whole install, step by step, is in [INSTALL.md](INSTALL.md); this is the short version. It runs on any machine on
the farm's network that reaches Farmhand's API port (4545) and the cameras, the YouTube plugin's machine included.

```bash
sudo mkdir -p /opt/farmhand-twitch && cd /opt/farmhand-twitch
sudo curl -fsSLo docker-compose.yml https://raw.githubusercontent.com/The-Original-Reth/farmhand-twitch-plugin/main/docker-compose.yml
sudo docker compose up -d --build
```

It answers at `http://<that machine>:8081`. Built from a copy of the repository instead (`docker build -t
farmhand-twitch .`), remove the compose file's `build:` line.

### An NVIDIA card

As in the YouTube plugin: ffmpeg compresses the stream on an NVIDIA card (NVENC) when the container can reach it, and on
the processor otherwise. The compose file has the `devices:` and library lines to uncomment, and the YouTube plugin's
README (["An NVIDIA card"](https://github.com/The-Original-Reth/farmhand-youtube-plugin#an-nvidia-card)) has the driver
set-up for a Proxmox container. Two plugins on one card each compress their own picture: consumer NVIDIA cards allow a
handful of these at once, plenty for two.

## Add it to Farmhand

1. In Farmhand, open the **Plugins** page (in the menu, under Settings).
2. Under **Add a plugin**, type its address, e.g. `http://192.168.10.215:8081`.
3. Farmhand shows what it wants: your printers' cameras and what they're printing. Say yes.
4. Farmhand shows `FARMHAND_URL` and `FARMHAND_TOKEN` **once**. Put them in `twitch.env` beside the compose file, and
   start it again: `sudo docker compose up -d --force-recreate`.

**Twitch** appears in Farmhand's menu. There, open **Twitch settings** and paste the stream key (on Twitch: Creator
Dashboard → Settings → Stream → Primary Stream key → Copy).

## Trying it out without Twitch

Set `STREAM_TEST_DESTINATION` to an RTMP receiver, e.g. [MediaMTX](https://github.com/bluenviron/mediamtx)
(`docker run -d --name mediamtx -p 1935:1935 -p 8554:8554 bluenviron/mediamtx:1.9.3`):

```
STREAM_TEST_DESTINATION=rtmp://192.168.10.215:1935/live
```

Paste any stream key in Twitch settings (e.g. `farmtest`): the stream goes to `rtmp://192.168.10.215:1935/live/farmtest`,
and Twitch is never sent anything. Watch it with `ffplay rtsp://192.168.10.215:8554/live/farmtest`.

## Settings (environment variables)

| Variable | What it is |
|---|---|
| `FARMHAND_URL`, `FARMHAND_TOKEN` | Where Farmhand's plugin API is, and this plugin's token (from the Plugins page) |
| `PORT` | Where it listens inside the container (8080; the compose file publishes it on 8081) |
| `STREAM_DATA` | Its settings folder (`/data`: a volume) |
| `STREAM_FOLDER` | The stream folder until a save location is set (`/media`: a mount) |
| `STREAM_FOLDER_SHOWN_AS` | Optional: the stream folder as people reach it over the network, shown on the page |
| `STREAM_CLIPS` | The clips folder until a save location is set (`/clips`: a mount) |
| `STREAM_CLIPS_SHOWN_AS` | Optional: the clips folder as people reach it over the network, shown on the page |
| `STREAM_TEST_DESTINATION` | Optional: an `rtmp://` address the stream goes to instead of Twitch |
| `FARMHAND_STREAM_ENCODER` | `auto` (default), `nvenc` or `cpu` |

## Developing

```bash
pip install -r requirements-dev.txt && python -m pytest -q
cd page && npm install && npm run build                      # the page, into streamer/web
STREAM_DATA=./data STREAM_FOLDER=./media python -m streamer  # the plugin on :8080 (ffmpeg on the PATH to go live)
cd page && npm run dev                                       # the page on :3638, its API passed to :8080
```

The history before the first Twitch commit is the YouTube plugin's, which this began as a copy of.
