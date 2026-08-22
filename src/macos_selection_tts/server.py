"""Foreground TTS server with interruptible, memory-only playback."""

from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass
import json
import logging
import os
import platform
import queue
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING, Any, Callable, Protocol

if TYPE_CHECKING:
    from spacy.language import Language

LOG = logging.getLogger("selection-tts")
SAMPLE_RATE = 24_000
MAX_TEXT_BYTES = 4 * 1024 * 1024
CHATTERBOX_PREBUFFER_SECONDS = 1.0
CHATTERBOX_BUFFERED_SENTENCES = 4
QUEUE_END = object()
INTERNAL_NEWLINES = re.compile(r"[^\S\r\n]*(?:\r\n?|\n)+[^\S\r\n]*")
LATEX_LINEBREAK_HYPHEN = re.compile(
    r"(?<=[^\W\d_])-[^\S\r\n]*(?:\r\n?|\n)[^\S\r\n]*(?=[^\W\d_])"
)


@dataclass(frozen=True)
class PreparedText:
    text: str
    sentences: tuple[str, ...]


class SpeechEngine(Protocol):
    def play(
        self,
        text: PreparedText,
        cancelled: threading.Event,
        paused: threading.Event,
    ) -> None: ...
    def stop(self) -> None: ...


def play_samples(
    stream: Any,
    samples: Any,
    sample_rate: int,
    cancelled: threading.Event,
    paused: threading.Event,
) -> bool:
    """Write audio in resumable blocks, retaining the current sample offset."""
    block_size = max(1, sample_rate // 10)
    for start in range(0, len(samples), block_size):
        if cancelled.is_set():
            return False
        if paused.is_set():
            stream.stop(ignore_errors=True)
            while paused.is_set() and not cancelled.wait(timeout=0.05):
                pass
            if cancelled.is_set():
                return False
            stream.start()
        stream.write(samples[start : start + block_size])
    return True


class KokoroEngine:
    """Own the Kokoro model and write generated chunks directly to CoreAudio."""

    def __init__(self, voice: str, speed: float, device: str) -> None:
        if device in {"auto", "mps"} and platform.system() == "Darwin":
            os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

        import sounddevice as sounddevice
        from kokoro import KPipeline

        requested_device = None if device == "auto" else device
        try:
            self.pipeline = KPipeline(
                lang_code="a",
                repo_id="hexgrad/Kokoro-82M",
                device=requested_device,
            )
        except RuntimeError:
            if device != "auto":
                raise
            LOG.warning("Automatic accelerator initialization failed; falling back to CPU")
            self.pipeline = KPipeline(
                lang_code="a",
                repo_id="hexgrad/Kokoro-82M",
                device="cpu",
            )

        self.pipeline.load_voice(voice)
        self.voice = voice
        self.speed = speed
        self.sounddevice = sounddevice
        self._stream_lock = threading.Lock()
        self._stream: Any | None = None

    def play(
        self,
        text: PreparedText,
        cancelled: threading.Event,
        paused: threading.Event,
    ) -> None:
        import numpy as np

        stream = self.sounddevice.OutputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
        )
        with self._stream_lock:
            self._stream = stream
        try:
            with stream:
                for result in self.pipeline(
                    text.text,
                    voice=self.voice,
                    speed=self.speed,
                    split_pattern=r"\n+",
                ):
                    if cancelled.is_set():
                        break
                    audio = result.audio
                    if audio is None:
                        continue
                    if hasattr(audio, "detach"):
                        audio = audio.detach().cpu().numpy()
                    samples = np.asarray(audio, dtype=np.float32).reshape(-1, 1)
                    if not play_samples(
                        stream,
                        samples,
                        SAMPLE_RATE,
                        cancelled,
                        paused,
                    ):
                        break
        finally:
            with self._stream_lock:
                if self._stream is stream:
                    self._stream = None

    def stop(self) -> None:
        with self._stream_lock:
            stream = self._stream
        if stream is not None:
            try:
                stream.abort(ignore_errors=True)
            except Exception:
                LOG.debug("Audio stream was already closed", exc_info=True)


class ChatterboxEngine:
    """Generate with Chatterbox Turbo and play from memory."""

    def __init__(self, device: str) -> None:
        import sounddevice as sounddevice
        import torch
        from chatterbox.tts_turbo import ChatterboxTurboTTS

        if device == "auto":
            device = "mps" if torch.backends.mps.is_available() else "cpu"

        self.model = ChatterboxTurboTTS.from_pretrained(device=device)
        self.sounddevice = sounddevice
        self._stream_lock = threading.Lock()
        self._stream: Any | None = None

    def play(
        self,
        text: PreparedText,
        cancelled: threading.Event,
        paused: threading.Event,
    ) -> None:
        import numpy as np
        from .chatterbox_streaming import stream_turbo

        def generate(sentence: str) -> Any:
            chunks = tuple(
                stream_turbo(
                    self.model,
                    sentence,
                    cancelled,
                    chunk_tokens=None,
                )
            )
            if not chunks:
                return np.empty((0, 1), dtype=np.float32)
            return np.concatenate(
                [np.asarray(chunk, dtype=np.float32).reshape(-1, 1) for chunk in chunks]
            )

        sentences = text.sentences or (text.text,)
        sentence_queue: queue.Queue[Any] = queue.Queue()
        audio_queue: queue.Queue[Any] = queue.Queue(
            maxsize=CHATTERBOX_BUFFERED_SENTENCES
        )
        for sentence in sentences:
            sentence_queue.put(sentence)
        sentence_queue.put(QUEUE_END)

        def put_audio(item: Any) -> bool:
            while not cancelled.is_set():
                try:
                    audio_queue.put(item, timeout=0.05)
                    return True
                except queue.Full:
                    continue
            return False

        def produce() -> None:
            try:
                while not cancelled.is_set():
                    sentence = sentence_queue.get()
                    if sentence is QUEUE_END:
                        break
                    if not put_audio(generate(sentence)):
                        return
            except Exception as error:
                put_audio(error)
            finally:
                put_audio(QUEUE_END)

        def take_audio() -> Any:
            while not cancelled.is_set():
                try:
                    item = audio_queue.get(timeout=0.05)
                except queue.Empty:
                    continue
                if isinstance(item, Exception):
                    raise item
                return item
            return QUEUE_END

        producer = threading.Thread(
            target=produce,
            name="chatterbox-generation",
            daemon=True,
        )
        producer.start()
        stream = self.sounddevice.OutputStream(
            samplerate=self.model.sr,
            channels=1,
            dtype="float32",
        )
        try:
            buffered: deque[Any] = deque()
            buffered_samples = 0
            target_samples = int(self.model.sr * CHATTERBOX_PREBUFFER_SECONDS)
            finished = False
            while buffered_samples < target_samples:
                audio = take_audio()
                if audio is QUEUE_END:
                    finished = True
                    break
                buffered.append(audio)
                buffered_samples += len(audio)

            if not buffered or cancelled.is_set():
                return

            with self._stream_lock:
                self._stream = stream
            with stream:
                while buffered and not cancelled.is_set():
                    if not play_samples(
                        stream,
                        buffered.popleft(),
                        self.model.sr,
                        cancelled,
                        paused,
                    ):
                        break
                while not finished and not cancelled.is_set():
                    audio = take_audio()
                    if audio is QUEUE_END:
                        finished = True
                    elif not play_samples(
                        stream,
                        audio,
                        self.model.sr,
                        cancelled,
                        paused,
                    ):
                        break
        finally:
            cancelled.set()
            producer.join()
            with self._stream_lock:
                if self._stream is stream:
                    self._stream = None

    def stop(self) -> None:
        with self._stream_lock:
            stream = self._stream
        if stream is not None:
            stream.abort(ignore_errors=True)


class PlaybackController:
    """Coordinate pause, resume, and replacement for one speech engine."""

    def __init__(self, engine: SpeechEngine) -> None:
        self.engine = engine
        self._operation_lock = threading.Lock()
        self._lock = threading.Lock()
        self._active = False
        self._paused = False
        self._generation = 0
        self._text: PreparedText | None = None
        self._cancelled: threading.Event | None = None
        self._pause_event: threading.Event | None = None
        self._thread: threading.Thread | None = None

    @property
    def active(self) -> bool:
        with self._lock:
            return self._active

    @property
    def paused(self) -> bool:
        with self._lock:
            return self._paused

    def toggle(self, text: PreparedText) -> str:
        with self._operation_lock:
            with self._lock:
                if not self._active:
                    self._start_locked(text)
                    return "started"

                if text == self._text:
                    pause_event = self._pause_event
                    if self._paused:
                        self._paused = False
                        if pause_event is not None:
                            pause_event.clear()
                        return "resumed"
                    self._paused = True
                    if pause_event is not None:
                        pause_event.set()
                    return "paused"

                cancelled, pause_event, thread = self._detach_locked()

            self._stop_worker(cancelled, pause_event, thread)

            with self._lock:
                self._start_locked(text)
            return "replaced"

    def _start_locked(self, text: PreparedText) -> None:
        self._active = True
        self._paused = False
        self._generation += 1
        generation = self._generation
        cancelled = threading.Event()
        pause_event = threading.Event()
        thread = threading.Thread(
            target=self._play,
            args=(generation, text, cancelled, pause_event),
            name="selection-tts-playback",
            daemon=True,
        )
        self._text = text
        self._cancelled = cancelled
        self._pause_event = pause_event
        self._thread = thread
        thread.start()

    def _detach_locked(
        self,
    ) -> tuple[threading.Event | None, threading.Event | None, threading.Thread | None]:
        self._active = False
        self._paused = False
        self._generation += 1
        cancelled = self._cancelled
        pause_event = self._pause_event
        thread = self._thread
        self._text = None
        self._cancelled = None
        self._pause_event = None
        self._thread = None
        return cancelled, pause_event, thread

    def _stop_worker(
        self,
        cancelled: threading.Event | None,
        pause_event: threading.Event | None,
        thread: threading.Thread | None,
    ) -> None:
        if pause_event is not None:
            pause_event.clear()
        if cancelled is not None:
            cancelled.set()
        self.engine.stop()
        if thread is not None:
            thread.join()

    def _play(
        self,
        generation: int,
        text: PreparedText,
        cancelled: threading.Event,
        paused: threading.Event,
    ) -> None:
        try:
            self.engine.play(text, cancelled, paused)
        except Exception:
            if not cancelled.is_set():
                LOG.exception("Speech generation or playback failed")
        finally:
            with self._lock:
                if self._generation == generation:
                    self._active = False
                    self._paused = False
                    self._text = None
                    self._cancelled = None
                    self._pause_event = None
                    self._thread = None

    def shutdown(self) -> None:
        with self._operation_lock:
            with self._lock:
                cancelled, pause_event, thread = self._detach_locked()
            self._stop_worker(cancelled, pause_event, thread)


def transform_sentence_spans(
    text: str,
    nlp: Language,
    transforms: tuple[Callable[[str], str], ...],
) -> str:
    """Apply text transforms to sentence content using spaCy character spans."""
    return prepare_sentence_spans(text, nlp, transforms).text


def prepare_sentence_spans(
    text: str,
    nlp: Language,
    transforms: tuple[Callable[[str], str], ...],
) -> PreparedText:
    """Transform text and retain its spaCy sentence boundaries."""
    parts: list[str] = []
    sentences: list[str] = []
    cursor = 0
    for sentence in nlp(text).sents:
        parts.append(text[cursor : sentence.start_char])
        span_text = text[sentence.start_char : sentence.end_char]
        content_start = len(span_text) - len(span_text.lstrip())
        content_end = len(span_text.rstrip())
        parts.append(span_text[:content_start])
        content = span_text[content_start:content_end]
        for transform in transforms:
            content = transform(content)
        if content:
            sentences.append(content)
        parts.append(content)
        parts.append(span_text[content_end:])
        cursor = sentence.end_char
    parts.append(text[cursor:])
    transformed = "".join(parts)
    return PreparedText(transformed, tuple(sentences))


def natural_flow(text: str, nlp: Language) -> str:
    """Replace newlines inside spaCy sentence spans while preserving boundaries."""
    return transform_sentence_spans(
        text,
        nlp,
        (lambda content: INTERNAL_NEWLINES.sub(" ", content),),
    )


def latex_flow(text: str, nlp: Language) -> str:
    """Join letter-hyphen-linebreak-letter sequences inside sentence spans."""
    return transform_sentence_spans(
        text,
        nlp,
        (lambda content: LATEX_LINEBREAK_HYPHEN.sub("", content),),
    )


def build_preprocessor(
    natural_flow_enabled: bool,
    latex: bool,
    segment_sentences: bool = False,
) -> Callable[[str], PreparedText]:
    if not natural_flow_enabled and not latex and not segment_sentences:
        return plain_text

    import spacy

    nlp = spacy.load("en_core_web_sm")
    transforms: list[Callable[[str], str]] = []
    if latex:
        transforms.append(lambda content: LATEX_LINEBREAK_HYPHEN.sub("", content))
    if natural_flow_enabled:
        transforms.append(lambda content: INTERNAL_NEWLINES.sub(" ", content))
    def preprocess(text: str) -> PreparedText:
        prepared = prepare_sentence_spans(text, nlp, tuple(transforms))
        return PreparedText(prepared.text.strip(), prepared.sentences)

    return preprocess


def plain_text(text: str) -> PreparedText:
    text = text.strip()
    return PreparedText(text, (text,) if text else ())


class SelectionRequestHandler(BaseHTTPRequestHandler):
    server: "SelectionHTTPServer"

    def do_POST(self) -> None:
        if self.path != "/speak":
            self.send_error(404)
            return
        try:
            size = int(self.headers.get("Content-Length", ""))
            if size < 0 or size > MAX_TEXT_BYTES:
                raise ValueError("invalid content length")
            text = self.server.preprocess(self.rfile.read(size).decode("utf-8"))
            if not text.text:
                self._reply(200, {"ok": True, "action": "empty"})
                return
            action = self.server.controller.toggle(text)
            self._reply(200, {"ok": True, "action": action})
        except (UnicodeDecodeError, ValueError) as error:
            self._reply(400, {"ok": False, "error": str(error)})

    def _reply(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        LOG.debug(format, *args)


class SelectionHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], controller: PlaybackController) -> None:
        self.controller = controller
        self.preprocess: Callable[[str], PreparedText] = plain_text
        super().__init__(address, SelectionRequestHandler)


class SelectionServer:
    def __init__(
        self,
        controller: PlaybackController,
        host: str,
        port: int,
        preprocess: Callable[[str], PreparedText] = plain_text,
    ) -> None:
        self.controller = controller
        self.httpd = SelectionHTTPServer((host, port), controller)
        self.httpd.preprocess = preprocess

    @property
    def address(self) -> tuple[str, int]:
        host, port = self.httpd.server_address
        return str(host), int(port)

    def serve_forever(self) -> None:
        LOG.info("Listening on http://%s:%s", *self.address)
        self.httpd.serve_forever()

    def close(self) -> None:
        self.httpd.server_close()
        self.controller.shutdown()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Speak selected text with local TTS")
    parser.add_argument(
        "--engine",
        choices=("kokoro", "chatterbox"),
        default="kokoro",
        help="TTS engine (default: kokoro)",
    )
    parser.add_argument(
        "--voice",
        default="af_heart",
        help="Kokoro voice ID; supported only by Kokoro (default: af_heart)",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="speech speed multiplier; supported only by Kokoro (default: 1.0)",
    )
    parser.add_argument(
        "--device",
        choices=("auto", "mps", "cpu"),
        default="auto",
        help="inference device for either engine (auto prefers Apple MPS)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="localhost HTTP port (default: 8765)",
    )
    parser.add_argument(
        "--natural-flow",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "within each spaCy sentence, replace line breaks with spaces "
            "(enabled by default)"
        ),
    )
    parser.add_argument(
        "--latex",
        action="store_true",
        help=(
            "join PDF-style hyphenated line wraps such as "
            "'specu-\\nlation' (disabled by default)"
        ),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.speed <= 0:
        raise SystemExit("--speed must be greater than zero")

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    if args.engine == "chatterbox":
        if args.speed != 1.0:
            raise SystemExit("--speed is only supported by Kokoro")
        LOG.info("Loading Chatterbox Turbo on %s...", args.device)
        engine: SpeechEngine = ChatterboxEngine(args.device)
    else:
        LOG.info("Loading Kokoro (%s on %s)...", args.voice, args.device)
        engine = KokoroEngine(args.voice, args.speed, args.device)
    preprocess = build_preprocessor(
        args.natural_flow,
        args.latex,
        segment_sentences=args.engine == "chatterbox",
    )
    controller = PlaybackController(engine)
    server = SelectionServer(controller, "127.0.0.1", args.port, preprocess)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOG.info("Stopping.")
    finally:
        server.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
