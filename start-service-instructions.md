# Start Speak Selection with Local TTS

From the project directory:

```sh
uv run selection-tts-server
```

For Chatterbox Turbo (after `uv sync --extra chatterbox`):

```sh
uv run --extra chatterbox selection-tts-server --engine chatterbox
```

Natural flow is enabled by default. Use `--no-natural-flow` to disable it.
Use `--latex` to join words split with a hyphen across paper line breaks.

Then:

1. Assign Option–S to **Speak Selection with Local TTS** under **Keyboard → Keyboard Shortcuts → Services**.
2. Select text and press Option–S.
3. Press Option–S again to pause. Press it once more to continue from the same
   position. Select different text and press Option–S to replace the current
   speech. Press Ctrl–C in the terminal to stop the server.
