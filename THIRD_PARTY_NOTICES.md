# Third-party notices

This project depends on third-party packages distributed under their own
licenses. Their source distributions and installed packages contain the
complete applicable license texts.

Core projects used directly:

- [Kokoro](https://github.com/hexgrad/kokoro) — Apache License 2.0
- [Kokoro-82M model](https://huggingface.co/hexgrad/Kokoro-82M) — Apache License 2.0
- [Chatterbox](https://github.com/resemble-ai/chatterbox) — MIT License
- [Chatterbox Turbo model](https://huggingface.co/ResembleAI/chatterbox-turbo) — MIT License
- [spaCy](https://github.com/explosion/spaCy) — MIT License
- [spaCy models](https://github.com/explosion/spacy-models) — model-specific licenses
- [NumPy](https://github.com/numpy/numpy) — BSD 3-Clause License
- [python-sounddevice](https://github.com/spatialaudio/python-sounddevice) — MIT License
- [uv](https://github.com/astral-sh/uv) — MIT or Apache License 2.0

## Chatterbox TTS

Portions of `src/macos_selection_tts/chatterbox_streaming.py` adapt Chatterbox
TTS internals from [Resemble AI's Chatterbox repository](https://github.com/resemble-ai/chatterbox),
pinned in this project to commit
`5de7a54aa4e5e2baadb0182dde554908b48b85c2`.

The T3 inference portions carry the following MIT notice. The S3Gen flow
portions are modified from CosyVoice code credited to Alibaba Inc. and remain
subject to Apache License 2.0; see `APACHE-2.0.txt`. Both adapted portions were
changed for incremental, cancellable generation and memory-only playback.

MIT License

Copyright (c) 2025 Resemble AI

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## S3Gen / CosyVoice

Copyright (c) 2024 Alibaba Inc. (authors: Xiang Lyu, Zhihao Du)

Licensed under the Apache License, Version 2.0. A complete copy is provided in
`APACHE-2.0.txt`.
