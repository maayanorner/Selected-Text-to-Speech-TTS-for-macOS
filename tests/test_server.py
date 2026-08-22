import threading
import time
import json
from types import SimpleNamespace
from urllib.request import Request, urlopen

import numpy as np
import spacy

from macos_selection_tts.server import (
    ChatterboxEngine,
    PlaybackController,
    PreparedText,
    SelectionServer,
    build_parser,
    latex_flow,
    natural_flow,
    play_samples,
    prepare_sentence_spans,
)


class FakeEngine:
    def __init__(self):
        self.started = threading.Event()
        self.stopped = threading.Event()
        self.text = None

    def play(self, text, cancelled, paused):
        self.text = text
        self.started.set()
        cancelled.wait(timeout=2)

    def stop(self):
        self.stopped.set()


def test_toggle_pauses_then_resumes_without_replacing_text():
    engine = FakeEngine()
    controller = PlaybackController(engine)

    first = PreparedText("first selection", ("first selection",))
    assert controller.toggle(first) == "started"
    assert engine.started.wait(timeout=1)
    assert controller.active

    assert controller.toggle(first) == "paused"
    assert controller.active
    assert controller.paused
    assert engine.text == first

    assert controller.toggle(first) == "resumed"
    assert controller.active
    assert not controller.paused
    assert engine.text == first

    controller.shutdown()
    assert engine.stopped.wait(timeout=1)
    assert not controller.active


def test_new_selection_replaces_current_playback():
    class RecordingEngine:
        def __init__(self):
            self.plays = []
            self.played = threading.Condition()

        def play(self, text, cancelled, paused):
            with self.played:
                self.plays.append((text, cancelled))
                self.played.notify_all()
            cancelled.wait(timeout=2)

        def stop(self):
            return None

        def wait_for_plays(self, count):
            with self.played:
                return self.played.wait_for(
                    lambda: len(self.plays) >= count,
                    timeout=1,
                )

    engine = RecordingEngine()
    controller = PlaybackController(engine)
    first = PreparedText("first selection", ("first selection",))
    second = PreparedText("second selection", ("second selection",))

    assert controller.toggle(first) == "started"
    assert engine.wait_for_plays(1)
    first_cancelled = engine.plays[0][1]

    assert controller.toggle(second) == "replaced"
    assert engine.wait_for_plays(2)
    assert first_cancelled.is_set()
    assert [play[0] for play in engine.plays] == [first, second]
    assert controller.active
    assert not controller.paused

    controller.shutdown()


def test_replacement_does_not_wait_for_cancelled_worker():
    release = threading.Event()

    class SlowCancellationEngine:
        def __init__(self):
            self.plays = []
            self.started = threading.Event()

        def play(self, text, cancelled, paused):
            self.plays.append(text)
            self.started.set()
            if len(self.plays) == 1:
                release.wait(timeout=2)

        def stop(self):
            return None

    engine = SlowCancellationEngine()
    controller = PlaybackController(engine)
    first = PreparedText("first", ("first",))
    second = PreparedText("second", ("second",))

    assert controller.toggle(first) == "started"
    assert engine.started.wait(timeout=1)

    started = time.monotonic()
    assert controller.toggle(second) == "replaced"
    assert time.monotonic() - started < 0.2
    assert engine.plays == [first]

    release.set()
    for _ in range(100):
        if engine.plays == [first, second]:
            break
        time.sleep(0.005)
    assert engine.plays == [first, second]
    controller.shutdown()


def test_natural_completion_returns_to_idle():
    class ImmediateEngine(FakeEngine):
        def play(self, text, cancelled, paused):
            self.text = text

    controller = PlaybackController(ImmediateEngine())
    assert controller.toggle(PreparedText("short", ("short",))) == "started"
    for _ in range(100):
        if not controller.active:
            break
        time.sleep(0.005)
    assert not controller.active


def test_audio_resumes_at_the_next_unplayed_block():
    paused = threading.Event()
    cancelled = threading.Event()
    first_written = threading.Event()
    writes = []

    class Stream:
        def write(self, samples):
            writes.extend(samples.tolist())
            if len(writes) == 1:
                paused.set()
                first_written.set()

        def stop(self, ignore_errors=True):
            return None

        def start(self):
            return None

    thread = threading.Thread(
        target=play_samples,
        args=(Stream(), np.arange(5), 10, cancelled, paused),
    )
    thread.start()
    assert first_written.wait(timeout=1)
    time.sleep(0.05)
    assert writes == [0]

    paused.clear()
    thread.join(timeout=1)

    assert writes == [0, 1, 2, 3, 4]


def test_natural_flow_removes_only_intrasentence_newlines():
    nlp = spacy.blank("en")
    nlp.add_pipe("sentencizer")
    text = "This sentence\ncontinues.\nSecond sentence\nalso continues."

    assert natural_flow(text, nlp) == (
        "This sentence continues.\nSecond sentence also continues."
    )


def test_latex_flow_joins_hyphenated_line_breaks():
    nlp = spacy.blank("en")
    nlp.add_pipe("sentencizer")

    assert latex_flow("Some specu-\nlation follows.", nlp) == (
        "Some speculation follows."
    )


def test_preprocessing_retains_spacy_sentence_spans():
    nlp = spacy.blank("en")
    nlp.add_pipe("sentencizer")

    prepared = prepare_sentence_spans(
        "First line\ncontinues. Second sentence.",
        nlp,
        (lambda content: content.replace("\n", " "),),
    )

    assert prepared.text == "First line continues. Second sentence."
    assert prepared.sentences == ("First line continues.", "Second sentence.")


def test_preprocessing_flag_defaults():
    args = build_parser().parse_args([])

    assert args.engine == "kokoro"
    assert args.natural_flow is True
    assert args.latex is False


def test_chatterbox_option():
    args = build_parser().parse_args(["--engine", "chatterbox"])

    assert args.engine == "chatterbox"


def test_chatterbox_builds_a_multi_sentence_reserve(monkeypatch):
    from macos_selection_tts import chatterbox_streaming

    third_started = threading.Event()
    writes = []

    def generate(model, sentence, cancelled, *, chunk_tokens):
        assert chunk_tokens is None
        if sentence == "Third.":
            third_started.set()
        value = {"First.": 1, "Second.": 2, "Third.": 3}[sentence]
        yield np.full((1, 2), value, dtype=np.float32)
        yield np.full((1, 2), value, dtype=np.float32)

    class OutputStream:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def write(self, samples):
            if not writes:
                assert third_started.wait(timeout=1)
            writes.append(samples.copy())

        def abort(self, ignore_errors=True):
            return None

        def stop(self, ignore_errors=True):
            return None

        def start(self):
            return None

    monkeypatch.setattr(chatterbox_streaming, "stream_turbo", generate)
    engine = ChatterboxEngine.__new__(ChatterboxEngine)
    engine.model = SimpleNamespace(sr=24_000)
    engine.sounddevice = SimpleNamespace(OutputStream=lambda **kwargs: OutputStream())
    engine._stream_lock = threading.Lock()
    engine._stream = None

    engine.play(
        PreparedText(
            "First. Second. Third.",
            ("First.", "Second.", "Third."),
        ),
        threading.Event(),
        threading.Event(),
    )

    assert [samples[:, 0].tolist() for samples in writes] == [
        [1, 1, 1, 1],
        [2, 2, 2, 2],
        [3, 3, 3, 3],
    ]


def test_http_endpoint_accepts_selected_text():
    engine = FakeEngine()
    controller = PlaybackController(engine)
    server = SelectionServer(controller, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.address

    try:
        request = Request(
            f"http://{host}:{port}/speak",
            data="  Safari selection  ".encode(),
            method="POST",
        )
        with urlopen(request, timeout=2) as response:
            payload = json.load(response)

        assert payload == {"ok": True, "action": "started"}
        assert engine.started.wait(timeout=1)
        assert engine.text == PreparedText("Safari selection", ("Safari selection",))
    finally:
        server.httpd.shutdown()
        thread.join(timeout=2)
        server.close()
