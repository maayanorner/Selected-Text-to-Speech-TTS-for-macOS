# Speak Selection with Local TTS

Speak selected text in macOS applications with the local
[Kokoro-82M](https://github.com/hexgrad/kokoro) model.
Chatterbox Turbo is available as an optional engine.

## Requirements

- macOS
- [`uv`](https://docs.astral.sh/uv/)

No Homebrew packages are required.

## Install

```sh
./scripts/install-quick-action.sh
```

The installer creates a project-local Python environment, copies the Quick
Action to `~/Library/Services`, and refreshes the macOS Services cache. It does
not install a background service or login item. When upgrading from the former
Kokoro-named action, it removes that obsolete workflow to avoid duplicates.

See [start-service-instructions.md](start-service-instructions.md) to configure
Option-S and use it. Repeated presses pause and resume the current selection
without restarting it. Selecting different text and pressing Option-S replaces
the current speech with the new selection.

Generated audio is played from memory and never saved to disk. Model weights
are downloaded to the Hugging Face cache on first startup.

## Chatterbox Turbo

Install Chatterbox into the project environment:

```sh
uv sync --extra chatterbox
```

Run it:

```sh
uv run --extra chatterbox selection-tts-server --engine chatterbox
```

It uses the built-in English voice and selects Apple MPS automatically. Each
spaCy sentence is buffered in memory before playback. A continuous model worker
keeps up to four completed sentences ready while audio plays, so any generation
delay occurs between sentences rather than inside one.

## Text preprocessing

Natural flow is enabled by default. It uses spaCy sentence spans to remove
newlines inside a sentence while preserving sentence boundaries:

```sh
uv run selection-tts-server --natural-flow
uv run selection-tts-server --no-natural-flow
```

The implementation is `natural_flow` in `src/macos_selection_tts/server.py`.

For text copied from papers, `--latex` joins letter-hyphen-linebreak-letter
sequences such as `specu-\nlation`. It is disabled by default:

```sh
uv run selection-tts-server --latex
```

## Uninstall

```sh
./scripts/uninstall-quick-action.sh
```

This removes only the Quick Action. The project environment and reusable model
cache remain.

## Development

```sh
uv sync
uv run pytest
```
