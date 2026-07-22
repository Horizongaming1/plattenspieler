from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote

import numpy as np
import paho.mqtt.client as mqtt


LOGGER = logging.getLogger("turntable")
STOP = threading.Event()


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def env_int(name: str, default: int) -> int:
    value = env(name)
    return int(value) if value else default


def env_float(name: str, default: float) -> float:
    value = env(name)
    return float(value) if value else default


def env_bool(name: str, default: bool = False) -> bool:
    value = env(name)
    if not value:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    audio_device: str = env("AUDIO_DEVICE", "plughw:1,0")
    audio_input_channels: int = env_int("AUDIO_INPUT_CHANNELS", 2)
    audio_input_rate: int = env_int("AUDIO_INPUT_RATE", 44100)

    rms_on_threshold: float = env_float("RMS_ON_THRESHOLD", 0.025)
    rms_off_threshold: float = env_float("RMS_OFF_THRESHOLD", 0.015)
    rms_window_seconds: float = env_float("RMS_WINDOW_SECONDS", 0.5)
    rms_sample_rate: int = env_int("RMS_SAMPLE_RATE", 16000)
    silence_timeout_seconds: float = env_float("SILENCE_TIMEOUT_SECONDS", 180.0)
    level_log_interval_seconds: float = env_float("LEVEL_LOG_INTERVAL_SECONDS", 10.0)

    mqtt_host: str = env("MQTT_HOST")
    mqtt_port: int = env_int("MQTT_PORT", 1883)
    mqtt_user: str = env("MQTT_USER")
    mqtt_password: str = env("MQTT_PASSWORD")
    mqtt_client_id: str = env("MQTT_CLIENT_ID", "turntable-bridge")
    mqtt_state_topic: str = env("MQTT_STATE_TOPIC", "home/turntable/state")
    mqtt_availability_topic: str = env(
        "MQTT_AVAILABILITY_TOPIC", "home/turntable/availability"
    )
    mqtt_discovery_enable: bool = env_bool("MQTT_DISCOVERY_ENABLE", False)
    mqtt_discovery_prefix: str = env("MQTT_DISCOVERY_PREFIX", "homeassistant")
    mqtt_discovery_object_id: str = env(
        "MQTT_DISCOVERY_OBJECT_ID", "plattenspieler_aktiv"
    )
    mqtt_device_name: str = env("MQTT_DEVICE_NAME", "Plattenspieler")
    mqtt_unique_id: str = env("MQTT_UNIQUE_ID", "turntable_bridge_active")

    icecast_host: str = env("ICECAST_HOST", "icecast")
    icecast_port: int = env_int("ICECAST_PORT", 8000)
    icecast_mount: str = env("ICECAST_MOUNT", "turntable.mp3").lstrip("/")
    icecast_source_user: str = env("ICECAST_SOURCE_USER", "source")
    icecast_source_password: str = env("ICECAST_SOURCE_PASSWORD", "")

    stream_bitrate: str = env("STREAM_BITRATE", "192k")
    stream_channels: int = env_int("STREAM_CHANNELS", 2)
    stream_sample_rate: int = env_int("STREAM_SAMPLE_RATE", 44100)

    ffmpeg_loglevel: str = env("FFMPEG_LOGLEVEL", "warning")
    ffmpeg_low_latency: bool = env_bool("FFMPEG_LOW_LATENCY", True)
    ffmpeg_input_queue_size: int = env_int("FFMPEG_INPUT_QUEUE_SIZE", 16)
    ffmpeg_restart_delay_seconds: float = env_float(
        "FFMPEG_RESTART_DELAY_SECONDS", 5.0
    )

    def validate(self) -> None:
        if not self.icecast_source_password:
            raise ValueError("ICECAST_SOURCE_PASSWORD must be set")
        if self.rms_off_threshold > self.rms_on_threshold:
            raise ValueError("RMS_OFF_THRESHOLD must be <= RMS_ON_THRESHOLD")
        if self.rms_window_seconds <= 0:
            raise ValueError("RMS_WINDOW_SECONDS must be > 0")
        if self.silence_timeout_seconds <= 0:
            raise ValueError("SILENCE_TIMEOUT_SECONDS must be > 0")
        if self.ffmpeg_input_queue_size <= 0:
            raise ValueError("FFMPEG_INPUT_QUEUE_SIZE must be > 0")

    @property
    def icecast_url(self) -> str:
        user = quote(self.icecast_source_user, safe="")
        password = quote(self.icecast_source_password, safe="")
        mount = quote(self.icecast_mount, safe="/")
        return (
            f"icecast://{user}:{password}@"
            f"{self.icecast_host}:{self.icecast_port}/{mount}"
        )


class MqttPublisher:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.client: Optional[mqtt.Client] = None
        self.enabled = bool(config.mqtt_host)
        self.last_state: Optional[str] = None

    def start(self) -> None:
        if not self.enabled:
            LOGGER.warning("MQTT_HOST is empty; MQTT publishing is disabled")
            return

        try:
            client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION2,
                client_id=self.config.mqtt_client_id,
            )
        except (AttributeError, TypeError):
            client = mqtt.Client(client_id=self.config.mqtt_client_id)

        if self.config.mqtt_user:
            client.username_pw_set(self.config.mqtt_user, self.config.mqtt_password)

        client.will_set(
            self.config.mqtt_availability_topic,
            payload="offline",
            qos=1,
            retain=True,
        )
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.reconnect_delay_set(min_delay=2, max_delay=60)

        self.client = client
        client.connect_async(self.config.mqtt_host, self.config.mqtt_port, keepalive=30)
        client.loop_start()
        LOGGER.info(
            "MQTT connecting to %s:%s", self.config.mqtt_host, self.config.mqtt_port
        )

    def stop(self) -> None:
        if not self.client:
            return
        self.publish_availability("offline")
        self.client.loop_stop()
        self.client.disconnect()

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        LOGGER.info("MQTT connected: %s", reason_code)
        self.publish_availability("online")
        self.publish_discovery()
        if self.last_state:
            self.publish_state(self.last_state)

    def _on_disconnect(self, client, userdata, *args):
        reason_code = args[-2] if len(args) >= 2 else args[0] if args else "unknown"
        LOGGER.warning("MQTT disconnected: %s", reason_code)

    def publish_availability(self, value: str) -> None:
        if self.client:
            self.client.publish(
                self.config.mqtt_availability_topic,
                payload=value,
                qos=1,
                retain=True,
            )

    def publish_state(self, value: str) -> None:
        self.last_state = value
        if not self.client:
            return
        info = self.client.publish(
            self.config.mqtt_state_topic,
            payload=value,
            qos=1,
            retain=True,
        )
        LOGGER.info("MQTT state published: %s (mid=%s)", value, info.mid)

    def publish_discovery(self) -> None:
        if not self.client or not self.config.mqtt_discovery_enable:
            return
        topic = (
            f"{self.config.mqtt_discovery_prefix}/binary_sensor/"
            f"{self.config.mqtt_discovery_object_id}/config"
        )
        payload = {
            "name": "Plattenspieler aktiv",
            "unique_id": self.config.mqtt_unique_id,
            "state_topic": self.config.mqtt_state_topic,
            "availability_topic": self.config.mqtt_availability_topic,
            "payload_on": "ON",
            "payload_off": "OFF",
            "device_class": "sound",
            "device": {
                "identifiers": ["turntable_bridge"],
                "name": self.config.mqtt_device_name,
                "manufacturer": "local",
                "model": "Docker ALSA/Icecast bridge",
            },
        }
        self.client.publish(topic, json.dumps(payload), qos=1, retain=True)
        LOGGER.info("MQTT discovery published: %s", topic)


class LevelDetector:
    def __init__(self, config: Config, mqtt_publisher: MqttPublisher) -> None:
        self.config = config
        self.mqtt = mqtt_publisher
        self.active = False
        self.last_sound_at = 0.0
        self.last_log_at = 0.0

    def handle_pcm(self, data: bytes) -> None:
        if not data:
            return
        samples = np.frombuffer(data, dtype=np.int16)
        if samples.size == 0:
            return

        normalized = samples.astype(np.float32) / 32768.0
        rms = float(np.sqrt(np.mean(np.square(normalized))))
        now = time.monotonic()

        if rms >= self.config.rms_on_threshold:
            self.last_sound_at = now
            self.set_active(True)
        elif self.active and rms >= self.config.rms_off_threshold:
            self.last_sound_at = now
        elif (
            self.active
            and now - self.last_sound_at >= self.config.silence_timeout_seconds
        ):
            self.set_active(False)

        if now - self.last_log_at >= self.config.level_log_interval_seconds:
            self.last_log_at = now
            silence_for = (
                max(0.0, now - self.last_sound_at) if self.last_sound_at else 0.0
            )
            LOGGER.info(
                "level rms=%.5f state=%s silence_for=%.1fs",
                rms,
                "ON" if self.active else "OFF",
                silence_for,
            )

    def set_active(self, active: bool) -> None:
        if self.active == active:
            return
        self.active = active
        self.mqtt.publish_state("ON" if active else "OFF")
        LOGGER.info("turntable state changed: %s", "ON" if active else "OFF")


def build_ffmpeg_command(config: Config) -> list[str]:
    command = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        config.ffmpeg_loglevel,
    ]

    if config.ffmpeg_low_latency:
        command += [
            "-fflags",
            "nobuffer",
            "-flags",
            "low_delay",
        ]

    command += [
        "-f",
        "alsa",
        "-thread_queue_size",
        str(config.ffmpeg_input_queue_size if config.ffmpeg_low_latency else 1024),
        "-ac",
        str(config.audio_input_channels),
        "-ar",
        str(config.audio_input_rate),
        "-i",
        config.audio_device,
        "-map",
        "0:a:0",
        "-ac",
        str(config.stream_channels),
        "-ar",
        str(config.stream_sample_rate),
        "-codec:a",
        "libmp3lame",
    ]

    if config.ffmpeg_low_latency:
        command += [
            "-compression_level",
            "0",
            "-write_xing",
            "0",
            "-muxdelay",
            "0",
            "-muxpreload",
            "0",
            "-flush_packets",
            "1",
            "-max_delay",
            "0",
        ]

    command += [
        "-b:a",
        config.stream_bitrate,
        "-content_type",
        "audio/mpeg",
        "-f",
        "mp3",
        config.icecast_url,
        "-map",
        "0:a:0",
        "-ac",
        "1",
        "-ar",
        str(config.rms_sample_rate),
        "-f",
        "s16le",
        "pipe:1",
    ]
    return command


def log_ffmpeg_stderr(proc: subprocess.Popen[bytes]) -> None:
    assert proc.stderr is not None
    for raw_line in iter(proc.stderr.readline, b""):
        line = raw_line.decode("utf-8", errors="replace").strip()
        if line:
            if "non monotonically increasing dts" in line:
                continue
            LOGGER.warning("ffmpeg: %s", line)


def run_ffmpeg_once(config: Config, detector: LevelDetector) -> int:
    command = build_ffmpeg_command(config)
    redacted = [
        "<icecast-url>" if part.startswith("icecast://") else part
        for part in command
    ]
    LOGGER.info("starting ffmpeg: %s", " ".join(redacted))

    proc = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )
    stderr_thread = threading.Thread(
        target=log_ffmpeg_stderr,
        args=(proc,),
        name="ffmpeg-stderr",
        daemon=True,
    )
    stderr_thread.start()

    assert proc.stdout is not None
    chunk_size = max(1, int(config.rms_sample_rate * config.rms_window_seconds)) * 2

    try:
        while not STOP.is_set():
            data = proc.stdout.read(chunk_size)
            if not data:
                break
            detector.handle_pcm(data)
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)

    return proc.returncode if proc.returncode is not None else 0


def install_signal_handlers() -> None:
    def stop(signum, frame):
        LOGGER.info("received signal %s; stopping", signum)
        STOP.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    install_signal_handlers()

    config = Config()
    config.validate()

    LOGGER.info(
        "audio device=%s input=%sch/%sHz",
        config.audio_device,
        config.audio_input_channels,
        config.audio_input_rate,
    )
    LOGGER.info(
        "stream target=icecast://%s:%s/%s bitrate=%s",
        config.icecast_host,
        config.icecast_port,
        config.icecast_mount,
        config.stream_bitrate,
    )

    publisher = MqttPublisher(config)
    detector = LevelDetector(config, publisher)
    publisher.start()
    publisher.publish_state("OFF")

    try:
        while not STOP.is_set():
            exit_code = run_ffmpeg_once(config, detector)
            if STOP.is_set():
                break
            detector.set_active(False)
            LOGGER.error(
                "ffmpeg exited with code %s; restarting in %.1fs",
                exit_code,
                config.ffmpeg_restart_delay_seconds,
            )
            STOP.wait(config.ffmpeg_restart_delay_seconds)
    finally:
        detector.set_active(False)
        publisher.stop()

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        LOGGER.exception("fatal error")
        raise SystemExit(1)
