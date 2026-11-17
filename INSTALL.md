# Installing the Twitch plugin on a Farmhand

The plugin is a Docker container of its own, on Farmhand's machine or any machine on the network that can reach
Farmhand (port 4545) and the cameras. It can share a machine with the YouTube plugin: it uses port 8081 and folders of
its own.

The addresses here are examples (`192.168.10.240` the NAS, `192.168.10.90` Farmhand, `192.168.10.215` the plugin's
machine). Use your own.

## 1. Prepare the machine

Install **Docker** and **git** (Docker builds the plugin straight from GitHub). Nothing else: the plugin connects to
the NAS itself once you give it the address in Farmhand (section 6).

**On a Proxmox container (LXC)**, it must be allowed to mount network shares, as Farmhand's own container is. On the
Proxmox host, in `/etc/pve/lxc/<id>.conf`:

```
features: nesting=1,mount=cifs;nfs
lxc.apparmor.profile: unconfined
```

then restart the container. (A container that already runs the YouTube plugin has this.)

## 2. Get the compose file

```bash
sudo mkdir -p /opt/farmhand-twitch && cd /opt/farmhand-twitch
```

```bash
sudo curl -fsSLo docker-compose.yml https://raw.githubusercontent.com/The-Original-Reth/farmhand-twitch-plugin/main/docker-compose.yml
```

It's ready as it is. Only for an **NVIDIA card**, edit it and uncomment the `devices:` and library lines:

```bash
sudo nano /opt/farmhand-twitch/docker-compose.yml
```

## 3. Start it

```bash
cd /opt/farmhand-twitch && sudo docker compose up -d --build
```

It answers at `http://<that machine>:8081`, but doesn't know Farmhand yet.

## 4. Add it in Farmhand

1. Open **Plugins** (left-hand menu, under Settings).
2. Under **Add a plugin**, type its address, e.g. `http://192.168.10.215:8081`, and press **Look at it**.
3. Farmhand lists what it asks to read:
   - `cameras:read`: your printers' camera addresses
   - `prints:read`: what each printer is printing
4. Leave **Only accept its token from its own address** ticked (the token is then useless anywhere else).
5. Press **Add Twitch Stream**. The window **"Give Twitch Stream its token"** shows:
   ```
   FARMHAND_URL=http://192.168.10.90:4545/plugin-api/v1
   FARMHAND_TOKEN=Abc123…   (a long random string)
   ```
6. Press **Copy**. **Farmhand shows the token only this once.** Only **Done** closes the window, so leave it open until
   section 5 is done.

## 5. Give the plugin its token

Paste the two lines into `twitch.env`, beside `docker-compose.yml`:

```bash
sudo nano /opt/farmhand-twitch/twitch.env
```

Restart the plugin so it reads them, then press **Done** in Farmhand:

```bash
cd /opt/farmhand-twitch && sudo docker compose up -d --force-recreate
```

**Lost the token?** On the Plugins page, press **New token…** on Twitch Stream, then **Make a new token**: put the new
one in `twitch.env` and restart as above.

## 6. Set it up

**1. Where it saves.** In Farmhand, open **Settings**. Under the **Twitch Stream** heading, give the NAS address (e.g.
`\\192.168.10.240\3d_Printing_Elves\Farmhand`), its username and password, and press **Use this location**. The plugin
makes two folders inside it:

- **Stream folder** `…\Farmhand\Twitch stream`: the stream's pictures, slideshows and music.
- **Twitch clips** `…\Farmhand\Twitch clips`: where **Save clip** puts its videos.

**2. The stream key.** **Twitch** is now in Farmhand's menu. There, press **Twitch settings**, paste your stream key
(on Twitch: Creator Dashboard → Settings → Stream → Primary Stream key → Copy) and **Save**. Set the stream's title and
category on Twitch (Creator Dashboard → Stream Manager → Edit Stream Info).

**3. Going live.** Choose the grid and cameras, and press **Go live**.

## Updating

```bash
cd /opt/farmhand-twitch && sudo docker compose up -d --build
```

The channel stays live: Twitch is shown the holding screen for about a minute while the delay fills again.

## If it won't connect to the NAS

- **"The plugin's container isn't allowed to mount network shares"**: the compose file is missing the `cap_add` and
  `security_opt` lines, or, on Proxmox, the container's `features` and AppArmor lines (section 1).
- **"The NAS refused the connection"**: check the username and password, and that the user may use that share.
- **"Couldn't reach …"**: check the address, that the NAS is on, and that the plugin's machine is on the same network.
