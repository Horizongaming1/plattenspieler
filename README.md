# Plattenspieler Bridge fuer OMV, Docker Compose und Home Assistant

Dieses Projekt liest ein USB-Audiointerface auf einem OMV/Debian-Server per ALSA, berechnet aus dem Eingangssignal einen RMS-Pegel, meldet `ON`/`OFF` per MQTT an Home Assistant und stellt parallel einen MP3-HTTP-Stream bereit:

```text
http://OMV-IP:8090/turntable.mp3
```

Die Streaming-Architektur nutzt Icecast. `ffmpeg` liest das ALSA-Geraet genau einmal, sendet MP3 an Icecast und gibt gleichzeitig PCM-Daten an die Python-Pegelerkennung weiter. Das ist robuster als ein einfacher `ffmpeg -listen 1`-HTTP-Server, weil Home Assistant, Music Assistant und HomePods bei Verbindungsabbruechen eine stabile Stream-URL erneut oeffnen koennen.

## Projektstruktur

```text
.
├── docker-compose.yml
├── Dockerfile
├── .env.example
├── requirements.txt
├── docker/
│   ├── icecast-entrypoint.sh
│   └── icecast.xml.template
├── home-assistant/
│   ├── configuration.yaml
│   ├── automation-play.yaml
│   ├── automation-stop.yaml
│   ├── automation-music-assistant-play.yaml
│   ├── automation-owntone-play.yaml
│   ├── automation-owntone-stop.yaml
│   ├── rest-owntone.yaml
│   └── custom_components/
│       └── turntable_media_source/
├── owntone/
│   └── media/
│       └── Plattenspieler.m3u
└── src/
    └── main.py
```

## 1. Audiointerface auf OMV finden

Auf dem OMV/Debian-Server:

```bash
arecord -l
arecord -L
cat /proc/asound/cards
lsusb
```

`arecord -l` zeigt Karten und Devices, zum Beispiel:

```text
card 1: USB [USB Audio CODEC], device 0: USB Audio [USB Audio]
```

Daraus wird meistens:

```text
hw:1,0
```

`hw:1,0` bedeutet Karte 1, Device 0. Wenn das Interface ein Format nicht direkt akzeptiert, ist `plughw:1,0` oft praktischer, weil ALSA einfache Konvertierungen uebernimmt. Starte deshalb meist mit:

```env
AUDIO_DEVICE=plughw:CARD=CODEC,DEV=0
```

Eine kurze Testaufnahme auf OMV:

```bash
arecord -D plughw:1,0 -f S16_LE -c 2 -r 44100 -d 10 test.wav
aplay test.wav
```

## 2. Konfiguration

Kopiere die Beispieldatei:

```bash
cp .env.example .env
```

Passe mindestens diese Werte in `.env` an:

```env
AUDIO_DEVICE=plughw:CARD=CODEC,DEV=0
MQTT_HOST=homeassistant.local
MQTT_USER=
MQTT_PASSWORD=
ICECAST_SOURCE_PASSWORD=ein-langes-passwort
ICECAST_ADMIN_PASSWORD=ein-anderes-langes-passwort
ICECAST_RELAY_PASSWORD=noch-ein-passwort
STREAM_PUBLIC_PORT=8090
```

Wenn Docker keinen Zugriff auf `/dev/snd` bekommt, pruefe die Audio-Gruppen-ID auf OMV:

```bash
getent group audio
```

Die Zahl hinter dem Gruppennamen kommt in `.env`:

```env
AUDIO_GROUP_ID=29
```

## 3. Auf dem Mac entwickeln

Auf dem Mac kannst du die Dateien bearbeiten und die Images bauen. Der Container kann dort normalerweise nicht sinnvoll auf ein Linux-ALSA-Geraet zugreifen, weil `/dev/snd` macOS nicht existiert.

Syntax und Build pruefen:

```bash
docker compose config
docker compose build
```

Der echte Audio-Test passiert auf OMV.

## 3a. GitHub Packages / GHCR

Das Repository enthaelt einen GitHub-Actions-Workflow unter `.github/workflows/container.yml`. Bei Push auf `main` baut er zwei Images und veroeffentlicht sie in GitHub Packages:

```text
ghcr.io/horizongaming1/plattenspieler-turntable:latest
ghcr.io/horizongaming1/plattenspieler-icecast:latest
```

Auf OMV kannst du dann statt lokalem Build die Package-Compose-Datei nutzen:

```bash
docker compose -f docker-compose.package.yml pull
docker compose -f docker-compose.package.yml up -d
```

Falls das GitHub-Repo anders heisst oder unter einem anderen Owner liegt, passe in `.env` diese Werte an:

```env
TURNTABLE_IMAGE=ghcr.io/horizongaming1/plattenspieler-turntable:latest
ICECAST_IMAGE=ghcr.io/horizongaming1/plattenspieler-icecast:latest
```

Bei privaten GitHub Packages muss OMV einmalig bei GHCR angemeldet werden:

```bash
echo GITHUB_TOKEN | docker login ghcr.io -u GITHUB_USER --password-stdin
```

## 4. Auf OMV deployen

Per `rsync`:

```bash
rsync -av --exclude .git --exclude .env ./ USER@OMV-IP:/srv/plattenspieler/
ssh USER@OMV-IP
cd /srv/plattenspieler
cp .env.example .env
nano .env
docker compose up -d --build
```

Wenn du die Images aus GitHub Packages verwenden willst:

```bash
docker compose -f docker-compose.package.yml up -d
```

Oder per Git:

```bash
git clone <dein-repo> /srv/plattenspieler
cd /srv/plattenspieler
cp .env.example .env
nano .env
docker compose up -d --build
```

Mit GitHub Packages nach dem Clone:

```bash
docker compose -f docker-compose.package.yml pull
docker compose -f docker-compose.package.yml up -d
```

## 4a. OMV Webinterface / Compose Plugin

Lege im OMV-Webinterface genau einen Shared Folder an:

```text
turntable
```

Dieser Shared Folder ist der Datenordner fuer den Stack. In `turntable.env` zeigt `TURNTABLE_HOST_PATH` explizit auf diesen OMV Shared Folder:

```env
TURNTABLE_HOST_PATH=/srv/dev-disk-by-uuid-ed0cc40b-12e9-481a-9c82-203c8a67d732/turntable
```

Die Compose-Datei bindet diesen Shared Folder und seine Unterordner in die Container:

```yaml
volumes:
  - ${TURNTABLE_HOST_PATH:-/srv/dev-disk-by-uuid-ed0cc40b-12e9-481a-9c82-203c8a67d732/turntable}:/turntable
  - ${TURNTABLE_HOST_PATH:-/srv/dev-disk-by-uuid-ed0cc40b-12e9-481a-9c82-203c8a67d732/turntable}/config:/config
  - ${TURNTABLE_HOST_PATH:-/srv/dev-disk-by-uuid-ed0cc40b-12e9-481a-9c82-203c8a67d732/turntable}/logs:/logs
```

Der Container selbst braucht keinen zusaetzlichen `working_dir:`-Eintrag. Das Image setzt intern bereits:

```text
WORKDIR /app
```

Vorgehen im OMV Compose Plugin:

1. Lege einen neuen Compose-Stack oder eine neue Compose-Datei an, z. B. `turntable`.
2. Setze als Projekt-/Workdir den Shared Folder `turntable`.
3. Fuege den Inhalt aus `docker-compose.package.yml` ein.
4. Lege im selben Compose-Projekt die Env-Datei `turntable.env` aus `.env.example` an und passe die Werte an.
5. Starte den Stack ueber "Up".

Wenn du das YAML direkt ins Webinterface kopierst, verwende fuer das Package-Deployment diese Variante:

```yaml
services:
  turntable:
    image: "${TURNTABLE_IMAGE:-ghcr.io/horizongaming1/plattenspieler-turntable:latest}"
    container_name: turntable-bridge
    env_file:
      - ./turntable.env
    environment:
      TZ: ${TZ:-Europe/Berlin}
    volumes:
      - ${TURNTABLE_HOST_PATH:-/srv/dev-disk-by-uuid-ed0cc40b-12e9-481a-9c82-203c8a67d732/turntable}:/turntable
      - ${TURNTABLE_HOST_PATH:-/srv/dev-disk-by-uuid-ed0cc40b-12e9-481a-9c82-203c8a67d732/turntable}/config:/config
      - ${TURNTABLE_HOST_PATH:-/srv/dev-disk-by-uuid-ed0cc40b-12e9-481a-9c82-203c8a67d732/turntable}/logs:/logs
    devices:
      - /dev/snd:/dev/snd
    group_add:
      - "${AUDIO_GROUP_ID:-29}"
    depends_on:
      - icecast
    restart: unless-stopped

  icecast:
    image: "${ICECAST_IMAGE:-ghcr.io/horizongaming1/plattenspieler-icecast:latest}"
    container_name: turntable-icecast
    env_file:
      - ./turntable.env
    environment:
      TZ: ${TZ:-Europe/Berlin}
    volumes:
      - ${TURNTABLE_HOST_PATH:-/srv/dev-disk-by-uuid-ed0cc40b-12e9-481a-9c82-203c8a67d732/turntable}:/turntable
      - ${TURNTABLE_HOST_PATH:-/srv/dev-disk-by-uuid-ed0cc40b-12e9-481a-9c82-203c8a67d732/turntable}/config:/config
      - ${TURNTABLE_HOST_PATH:-/srv/dev-disk-by-uuid-ed0cc40b-12e9-481a-9c82-203c8a67d732/turntable}/logs:/logs
    ports:
      - "${STREAM_PUBLIC_PORT:-8090}:8000"
    restart: unless-stopped
```

Logs:

```bash
docker compose logs -f
docker compose logs -f turntable
docker compose logs -f icecast
```

## 5. Stream testen

Im Browser, VLC oder per `curl`:

```bash
curl -I http://OMV-IP:8090/turntable.mp3
vlc http://OMV-IP:8090/turntable.mp3
```

Icecast hat auch eine Statusseite:

```text
http://OMV-IP:8090/
```

Hinweis zur Latenz: MP3 ueber Icecast ist stabil und kompatibel, aber nicht latenzfrei. Rechne grob mit einigen Sekunden, je nach Client-Puffer. Fuer Multiroom/HomePods ist Stabilitaet meist wichtiger als minimale Latenz. Falls du spaeter extrem niedrige Latenz brauchst, waeren PCM/WAV oder ein anderer Streaming-Transport moeglich, aber oft weniger komfortabel fuer Home Assistant und Music Assistant.

## 6. MQTT pruefen

Topics abonnieren:

```bash
mosquitto_sub -h MQTT-HOST -u MQTT-USER -P MQTT-PASSWORD -t 'home/turntable/#' -v
```

Du solltest sehen:

```text
home/turntable/availability online
home/turntable/state ON
home/turntable/state OFF
```

Alle MQTT-Publishes sind retained, damit Home Assistant nach einem Neustart den letzten Zustand kennt. `availability` nutzt `online`/`offline`.

Optional kann MQTT Discovery aktiviert werden:

```env
MQTT_DISCOVERY_ENABLE=true
```

Dann erzeugt Home Assistant den Binary Sensor automatisch. Alternativ nutzt du das YAML aus `home-assistant/configuration.yaml`.

## 7. Home Assistant einbinden

### OwnTone als AirPlay-Bridge

OwnTone kann als dritter Container im selben Stack laufen und dann selbst auf AirPlay-/HomePod-Ziele streamen. Wichtig ist `network_mode: host`, weil OwnTone fuer AirPlay/mDNS die direkte Netzwerksicht des NAS braucht.

Die Compose-Erweiterung liegt in:

```text
docker-compose.owntone.yml
```

Im OMV Compose Plugin kannst du den `owntone`-Service daraus in deinen bestehenden `turntable`-Stack uebernehmen. Er nutzt denselben Shared Folder:

```yaml
volumes:
  - ${TURNTABLE_HOST_PATH}/owntone/etc:/etc/owntone
  - ${TURNTABLE_HOST_PATH}/owntone/media:/srv/media
  - ${TURNTABLE_HOST_PATH}/owntone/cache:/var/cache/owntone
```

Lege auf OMV zusaetzlich diese Datei an:

```text
/srv/dev-disk-by-uuid-ed0cc40b-12e9-481a-9c82-203c8a67d732/turntable/owntone/media/Plattenspieler.m3u
```

Inhalt:

```m3u
#EXTM3U
#EXTINF:-1,Plattenspieler
http://127.0.0.1:8090/turntable.mp3
```

OwnTone importiert M3U-Dateien aus der Library. Wenn die Datei eine HTTP-URL enthaelt, wird sie als Internetradio/Radio-Stream erkannt.

Nach dem Start ist die OwnTone-Weboberflaeche erreichbar unter:

```text
http://nas1.local:3689/
```

Dort:

1. Library neu scannen.
2. `Plattenspieler` in den Radios/Playlists suchen.
3. AirPlay-Outputs `HomePod Links`, `HomePod Rechts` oder `Wohnzimmer` aktivieren.
4. Manuell Play testen.

Home Assistant soll danach ueber die offizielle OwnTone-Integration auf den OwnTone-Server zugreifen:

1. Home Assistant: `Einstellungen` -> `Geraete & Dienste`.
2. `Integration hinzufuegen`.
3. `OwnTone` auswaehlen.
4. Host:

```text
nas1.local
```

5. Port:

```text
3689
```

OwnTone kann auch automatisch entdeckt werden. Nach dem Einrichten erzeugt Home Assistant den OwnTone-Player und die OwnTone-Outputs. Die Outputs sind die AirPlay-Zonen, also z. B. `HomePod Links`, `HomePod Rechts` oder ein Stereo-/Wohnzimmer-Ziel. Playlists aus OwnTone werden in Home Assistant als Quellen behandelt, deshalb wird `Plattenspieler.m3u` dort als Source `Plattenspieler` nutzbar.

Beispiel-Automation zum Starten:

```yaml
alias: Plattenspieler OwnTone starten
mode: restart
trigger:
  - platform: state
    entity_id: binary_sensor.plattenspieler_aktiv
    to: "on"
action:
  - service: media_player.select_source
    target:
      entity_id: media_player.owntone_server
    data:
      source: "Plattenspieler"
  - service: media_player.turn_on
    target:
      entity_id:
        - media_player.owntone_output_homepod_links
        - media_player.owntone_output_homepod_rechts
  - service: media_player.media_play
    target:
      entity_id: media_player.owntone_server
```

Beispiel-Automation zum Stoppen:

```yaml
alias: Plattenspieler OwnTone stoppen
mode: single
trigger:
  - platform: state
    entity_id: binary_sensor.plattenspieler_aktiv
    to: "off"
action:
  - service: media_player.media_stop
    target:
      entity_id: media_player.owntone_server
  - service: media_player.turn_off
    target:
      entity_id:
        - media_player.owntone_output_homepod_links
        - media_player.owntone_output_homepod_rechts
```

Die Entity-IDs sind Platzhalter. Die echten IDs findest du nach dem Einrichten in Home Assistant unter `Entwicklerwerkzeuge` -> `Zustaende`, Filter `owntone`.

Optional kannst du OwnTone auch direkt per REST steuern. Dafuer liegen Beispiele in `home-assistant/rest-owntone.yaml`:

```yaml
rest_command:
  owntone_play:
    url: "http://nas1.local:3689/api/player/play"
    method: PUT

  owntone_stop:
    url: "http://nas1.local:3689/api/player/stop"
    method: PUT

  owntone_rescan:
    url: "http://nas1.local:3689/api/library/rescan"
    method: PUT
```

### Medienquelle

Damit der Stream im Home-Assistant-Medienbrowser als Quelle erscheint, kopiere den Ordner:

```text
home-assistant/custom_components/turntable_media_source
```

nach:

```text
/config/custom_components/turntable_media_source
```

Fuege danach in `configuration.yaml` hinzu:

```yaml
turntable_media_source:
  name: "Plattenspieler"
  url: "http://nas1.local:8090/turntable.mp3"
  mime_type: "audio/mpeg"
```

Starte Home Assistant danach neu. Anschliessend erscheint im Medienbrowser eine Quelle `Plattenspieler`. Die direkte Media-Source-ID fuer Automationen ist:

```text
media-source://turntable_media_source/turntable
```

Eine Play-Aktion kann dann so aussehen:

```yaml
action:
  - service: media_player.play_media
    target:
      entity_id: media_player.wohnzimmer
    data:
      media_content_id: "media-source://turntable_media_source/turntable"
      media_content_type: "audio/mpeg"
```

Hinweis: Die Medienquelle sorgt dafuer, dass Home Assistant den Stream im Medienbrowser und in `media-source://`-Automationen kennt. Ob ein bestimmter Player den Icecast-Stream wirklich abspielt, entscheidet weiterhin die jeweilige Player-Integration.

Beispiel fuer `configuration.yaml`:

```yaml
mqtt:
  binary_sensor:
    - name: "Plattenspieler aktiv"
      unique_id: plattenspieler_aktiv
      state_topic: "home/turntable/state"
      availability_topic: "home/turntable/availability"
      payload_on: "ON"
      payload_off: "OFF"
      device_class: sound

turntable_media_source:
  name: "Plattenspieler"
  url: "http://nas1.local:8090/turntable.mp3"
  mime_type: "audio/mpeg"
```

Automation zum Starten:

```yaml
alias: Plattenspieler Stream starten
mode: restart
trigger:
  - platform: state
    entity_id: binary_sensor.plattenspieler_aktiv
    to: "on"
action:
  - service: media_player.play_media
    target:
      entity_id: media_player.wohnzimmer
    data:
      media_content_id: "media-source://turntable_media_source/turntable"
      media_content_type: "audio/mpeg"
```

Automation zum Stoppen:

```yaml
alias: Plattenspieler Stream stoppen
mode: single
trigger:
  - platform: state
    entity_id: binary_sensor.plattenspieler_aktiv
    to: "off"
action:
  - service: media_player.media_stop
    target:
      entity_id: media_player.homepod
```

Music-Assistant-Beispiel:

```yaml
alias: Plattenspieler Music Assistant starten
mode: restart
trigger:
  - platform: state
    entity_id: binary_sensor.plattenspieler_aktiv
    to: "on"
action:
  - service: music_assistant.play_media
    target:
      entity_id: media_player.ma_wohnzimmer
    data:
      media_id: "http://OMV-IP:8090/turntable.mp3"
      media_type: "url"
```

Passe `media_player.homepod`, `media_player.ma_wohnzimmer` und `http://OMV-IP:8090/turntable.mp3` an deine Umgebung an.

## 8. Diagnose im Container

Audio-Geraete im Container:

```bash
docker exec -it turntable-bridge arecord -l
docker exec -it turntable-bridge arecord -L
docker exec -it turntable-bridge cat /proc/asound/cards
docker exec -it turntable-bridge ffmpeg -devices
```

Direkter ffmpeg-Test im Container:

```bash
docker exec -it turntable-bridge ffmpeg -f alsa -ac 2 -ar 44100 -i 'plughw:CARD=CODEC,DEV=0' -t 10 -f null -
```

Wenn das fehlschlaegt, stimmen meist `AUDIO_DEVICE`, Rechte auf `/dev/snd` oder `AUDIO_GROUP_ID` nicht.

## 9. Threshold kalibrieren

Starte die Container und beobachte die Logs:

```bash
docker compose logs -f turntable
```

Die App loggt etwa alle `LEVEL_LOG_INTERVAL_SECONDS` den aktuellen RMS-Wert:

```text
level rms=0.00312 state=OFF silence_for=0.0s
level rms=0.04851 state=ON silence_for=0.0s
```

Vorgehen:

1. Plattenspieler aus oder Nadel oben: notiere typische Ruhewerte.
2. Leise Platte starten: notiere typische Musikwerte.
3. Setze `RMS_ON_THRESHOLD` oberhalb des Ruhewerts und unterhalb leiser Musik.
4. Setze `RMS_OFF_THRESHOLD` niedriger als `RMS_ON_THRESHOLD`.
5. `SILENCE_TIMEOUT_SECONDS=180` verhindert, dass Pausen zwischen Titeln sofort `OFF` ausloesen.

Beispiel:

```env
RMS_ON_THRESHOLD=0.025
RMS_OFF_THRESHOLD=0.015
SILENCE_TIMEOUT_SECONDS=180
```

## 10. Fehlerverhalten

- MQTT reconnectet automatisch. Per Last Will wird `offline` publiziert, wenn der Container hart abbricht.
- Wenn `ffmpeg` oder das Audiointerface ausfaellt, startet die App den Prozess nach `FFMPEG_RESTART_DELAY_SECONDS` neu.
- Wenn Docker oder der Host neu startet, bringt `restart: unless-stopped` beide Dienste wieder hoch.
- Secrets gehoeren nur in `.env`; `.env` ist in `.gitignore` eingetragen.
