# Selected Text to Speech (TTS) for macOS

Speak selected text in macOS applications with a local TTS model. The project
provides the **Speak Selection with Local TTS** Quick Action and supports:

- [Kokoro-82M](https://github.com/hexgrad/kokoro), the default engine
- Chatterbox Turbo, an optional engine with sentence-buffered playback

Audio is played from memory and is not saved to disk.

## Requirements

- macOS
- [uv](https://docs.astral.sh/uv/)

No Homebrew packages or background services are required.

## Install

Clone or download this repository, open a terminal in its directory, and run:

```sh
./scripts/install-quick-action.sh
```

This command:

1. Creates the project-local `.venv` with uv and installs the default Kokoro
   dependencies there.
2. Installs **Speak Selection with Local TTS** in
   `~/Library/Services`.
3. Refreshes the macOS Services list.

It does not create a login item or background service.

### Optional: install Chatterbox Turbo

Install Chatterbox into the same project-local environment:

```sh
uv sync --extra chatterbox
```

No system-wide Python packages are installed.

## Configure the shortcut

Open **System Settings → Keyboard → Keyboard Shortcuts → Services**, find
**Speak Selection with Local TTS**, and assign Option–S. macOS does not let a
Quick Action supply its own default shortcut.

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
selection to macOS Services and press Option–S.

- Press Option–S again with the same text selected to pause.
- Press it once more with the same text selected to resume without restarting.
- Select different text and press Option–S to replace the current speech.
- Press Control–C in the terminal to stop the server.

## Command-line options

```text
--engine {kokoro,chatterbox}  TTS engine; defaults to kokoro
--voice VOICE                Kokoro voice; defaults to af_heart
--speed SPEED                Kokoro speed multiplier; defaults to 1.0
--device {auto,mps,cpu}       Inference device; auto prefers Apple MPS
--port PORT                   Local HTTP port; defaults to 8765
--natural-flow                Enable natural-flow preprocessing (default)
--no-natural-flow             Disable natural-flow preprocessing
--latex                       Join words split by hyphenated paper line breaks
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
