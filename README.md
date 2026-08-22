# 🗣️ Selected Text to Speech (TTS) for macOS 🍎

## About

💡 **Motivation:** I built this to read research papers aloud using local neural
TTS voices because the built-in macOS speech did not suit my preferences. Text copied
from papers also contains line breaks and hyphenated word splits that sound
unnatural when read literally, so the project includes sentence-aware
preprocessing for more natural speech.

🎯 **Goal:** Turn selected text 📝 in macOS applications into speech 🗣️ using a model
running locally. The project provides the **Speak Selection with Local TTS**
Quick Action, with pause/resume controls, text preprocessing, and memory-only
audio playback.

🤖 **Development:** This project was vibe-coded: it was built iteratively with
an AI coding agent and tested on macOS.

⚠️ **Disclaimer:** Use at your own risk. This is an experimental project
provided “as is,” without warranty, under the [MIT License](LICENSE). You are
responsible for how you use generated audio and for complying with applicable
laws and third-party licenses. This project is not affiliated with or endorsed
by the upstream model or library authors.

## How it works

<p align="center">
  🖱️ <strong>Select text with your mouse</strong>
  → ⌨️ <strong>Your shortcut</strong>
  → ⚡ <strong>Quick Action</strong>
  → 🧠 <strong>Local TTS</strong>
  → 🗣️ <strong>Speech</strong>
</p>

For example, use your mouse to select the highlighted span:

> The paper reports that <mark>speculative decoding reduces inference latency</mark>.

Only `speculative decoding reduces inference latency` is sent to the local TTS
server and spoken.

- Same selection + shortcut: pause or resume.
- Different selection + shortcut: replace the current speech.

In practice: start the local server in a terminal, select text in a macOS
application, and press your configured shortcut (for example, Option–S). Keep
the same text selected to pause or resume; select different text to replace the
current speech. Installation, shortcut configuration, and server commands are
described below.

It supports:

- [Kokoro-82M](https://github.com/hexgrad/kokoro), the default engine
- [Chatterbox Turbo](https://github.com/resemble-ai/chatterbox), an optional
  engine with sentence-buffered playback

Audio is played from memory and is not saved to disk.

## Requirements

- macOS
- [uv](https://docs.astral.sh/uv/)

No Homebrew packages or background services are required.

## Install

```sh
git clone https://github.com/maayanorner/Selected-Text-to-Speech-TTS-for-macOS.git
cd Selected-Text-to-Speech-TTS-for-macOS
uv sync --extra chatterbox  # --extra chatterbox is optional
./scripts/install-quick-action.sh
```

This installs both Kokoro and Chatterbox Turbo, then installs the macOS Quick
Action. It does not create a login item or background service.

## Configure the shortcut

Open **System Settings → Keyboard → Keyboard Shortcuts → Services**, find
**Speak Selection with Local TTS**, and assign your preferred shortcut (for
example, Option–S). **You need to define it yourself because Quick Action
shortcuts cannot be assigned cleanly by an installer: macOS provides no
supported command-line API for changing them.**

## Run

The server runs in the foreground. Start the default Kokoro engine from the
project directory:

```sh
uv run selection-tts-server
```

Or start Chatterbox Turbo:

```sh
uv run --extra chatterbox selection-tts-server --engine chatterbox
```

Keep that terminal open. Then select text in an application that exposes its
selection to macOS Services and press your configured shortcut.

- Press the shortcut again with the same text selected to pause.
- Press it once more with the same text selected to resume without restarting.
- Select different text and press the shortcut to replace the current speech.
- Press Control–C in the terminal to stop the server.

## Command-line options

```text
--engine {kokoro,chatterbox}  TTS engine; defaults to kokoro
--voice VOICE                Kokoro voice ID; Kokoro only; defaults to af_heart
--speed SPEED                Kokoro speed multiplier; Kokoro only; defaults to 1.0
--device {auto,mps,cpu}       Inference device for either engine; auto prefers Apple MPS
--port PORT                   Localhost HTTP port; defaults to 8765
--natural-flow                Within each spaCy sentence, replace line breaks with spaces; enabled by default
--no-natural-flow             Disable natural-flow newline replacement; --latex still applies if enabled
--latex                       Join PDF-style hyphenated line wraps, such as specu-\nlation; disabled by default
```

For example, run Chatterbox with paper-text preprocessing:

```sh
uv run --extra chatterbox selection-tts-server --engine chatterbox --latex
```

Use `uv run selection-tts-server --help` for the generated CLI help.

## Text preprocessing

Natural flow is enabled by default. It uses spaCy sentence spans to remove
newlines inside individual sentences while preserving sentence boundaries.

The optional `--latex` mode additionally joins a word broken across a line
break, such as `specu-\nlation`. It only joins a hyphen when a newline follows
it.

Chatterbox generates complete sentence buffers ahead of playback. One model
worker fills a bounded audio queue while previously generated speech plays.

## Files and model cache

The installer writes only the following project or user-local files:

- `.venv` inside the project directory
- `~/Library/Services/SelectedTextToSpeech.workflow`
- Model files downloaded by the engines to the standard Hugging Face cache on
  first use

No audio files are created.

## Uninstall the Quick Action

```sh
./scripts/uninstall-quick-action.sh
```

This removes only the Quick Action. It leaves the project `.venv` and model
cache intact.

## Development

```sh
uv sync
uv run pytest
```

## Built with

- [Kokoro](https://github.com/hexgrad/kokoro)
- [Kokoro-82M model](https://huggingface.co/hexgrad/Kokoro-82M)
- [Chatterbox](https://github.com/resemble-ai/chatterbox)
- [Chatterbox Turbo model](https://huggingface.co/ResembleAI/chatterbox-turbo)
- [spaCy](https://github.com/explosion/spaCy)
- [spaCy models](https://github.com/explosion/spacy-models)
- [NumPy](https://github.com/numpy/numpy)
- [python-sounddevice](https://github.com/spatialaudio/python-sounddevice)
- [uv](https://github.com/astral-sh/uv)

## License

The original code in this project is licensed under the [MIT License](LICENSE).
Third-party dependencies and adapted portions retain their original licenses
and copyright notices; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
