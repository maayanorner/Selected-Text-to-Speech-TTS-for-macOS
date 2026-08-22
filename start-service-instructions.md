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

1. Assign your preferred shortcut (for example, Option–S) to **Speak Selection
   with Local TTS** under **Keyboard → Keyboard Shortcuts → Services**.
2. Select text and press your configured shortcut.
3. Press the shortcut again to pause. Press it once more to continue from the
   same position. Select different text and press the shortcut to replace the
   current speech. Press Ctrl–C in the terminal to stop the server.
