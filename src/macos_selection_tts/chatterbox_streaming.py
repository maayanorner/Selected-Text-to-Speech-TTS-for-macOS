"""Incrementally decode speech with Chatterbox Turbo."""

# Original code in this file is licensed under the project's MIT License.
# Portions adapt Chatterbox T3 code (Copyright 2025 Resemble AI, MIT) and
# Chatterbox S3Gen/CosyVoice code (Copyright 2024 Alibaba Inc., Apache-2.0).
# See THIRD_PARTY_NOTICES.md and APACHE-2.0.txt.

from __future__ import annotations

from collections.abc import Iterator
from typing import Any


def stream_turbo(
    model: Any,
    text: str,
    cancelled: Any,
    *,
    chunk_tokens: int | None = 24,
) -> Iterator[Any]:
    """Yield CPU float32 waveform tensors while Turbo is generating tokens."""
    import torch

    with torch.inference_mode():
        yield from _stream_turbo(model, text, cancelled, chunk_tokens)


def _stream_turbo(
    model: Any,
    text: str,
    cancelled: Any,
    chunk_tokens: int | None,
) -> Iterator[Any]:
    import torch
    import torch.nn.functional as F
    from chatterbox.models.s3gen.const import S3GEN_SIL
    from chatterbox.models.s3tokenizer import SPEECH_VOCAB_SIZE
    from chatterbox.tts_turbo import punc_norm
    from transformers.generation.logits_process import (
        LogitsProcessorList,
        RepetitionPenaltyLogitsProcessor,
        TemperatureLogitsWarper,
        TopKLogitsWarper,
        TopPLogitsWarper,
    )

    text_tokens = model.tokenizer(
        punc_norm(text), return_tensors="pt", padding=True, truncation=True
    ).input_ids.to(model.device)
    t3 = model.t3
    processors = LogitsProcessorList(
        [
            TemperatureLogitsWarper(0.8),
            TopKLogitsWarper(1000),
            TopPLogitsWarper(0.95),
            RepetitionPenaltyLogitsProcessor(1.2),
        ]
    )
    start = t3.hp.start_speech_token * torch.ones_like(text_tokens[:, :1])
    embeds, _ = t3.prepare_input_embeds(
        t3_cond=model.conds.t3,
        text_tokens=text_tokens,
        speech_tokens=start,
        cfg_weight=0.0,
    )
    output = t3.tfmr(inputs_embeds=embeds, use_cache=True)
    past = output.past_key_values
    generated: list[Any] = []
    streamer = _S3Streamer(model.s3gen, model.conds.gen, S3GEN_SIL)

    for _ in range(1000):
        logits = t3.speech_head(output[0][:, -1:])[:, -1, :]
        history = torch.cat(generated, dim=1) if generated else start
        logits = processors(history, logits)
        if torch.all(logits == -torch.inf):
            break
        token = torch.multinomial(F.softmax(logits, dim=-1), num_samples=1)
        if torch.all(token == t3.hp.stop_speech_token):
            break
        generated.append(token)

        if int(token.item()) < SPEECH_VOCAB_SIZE:
            streamer.append(token)
            if chunk_tokens and streamer.token_count % chunk_tokens == 0:
                wav = streamer.flush()
                if wav is not None:
                    yield wav.detach().to(device="cpu", dtype=torch.float32)

        if cancelled.is_set():
            return
        output = t3.tfmr(
            inputs_embeds=t3.speech_emb(token),
            past_key_values=past,
            use_cache=True,
        )
        past = output.past_key_values

    if not cancelled.is_set():
        wav = streamer.finish()
        if wav is not None:
            yield wav.detach().to(device="cpu", dtype=torch.float32)


class _S3Streamer:
    """Decode growing S3-token prefixes while retaining overlap state."""

    def __init__(self, s3gen: Any, ref_dict: dict[str, Any], silence_token: int) -> None:
        import torch

        self.s3gen = s3gen
        self.ref_dict = ref_dict
        self.silence_token = silence_token
        self.tokens: list[Any] = []
        self.noise: Any | None = None
        self.source = torch.zeros(
            1, 1, 0, device=s3gen.device, dtype=s3gen.dtype
        )
        self.tail: Any | None = None
        self.emitted = 0
        self.crossfade = int(0.012 * 24_000)

    @property
    def token_count(self) -> int:
        return sum(token.shape[-1] for token in self.tokens)

    def append(self, token: Any) -> None:
        import torch

        self.tokens.append(
            torch.atleast_2d(token).to(device=self.s3gen.device, dtype=torch.long)
        )

    def flush(self, *, final: bool = False) -> Any | None:
        import torch

        tokens = torch.cat(self.tokens, dim=1)
        stable_tokens = tokens.shape[-1]
        if not final:
            stable_tokens -= self.s3gen.flow.pre_lookahead_len
        if stable_tokens <= 0:
            return None

        mel_frames = stable_tokens * self.s3gen.flow.token_mel_ratio
        if self.noise is None:
            self.noise = torch.randn(
                1, 80, mel_frames, device=self.s3gen.device, dtype=self.s3gen.dtype
            )
        elif self.noise.shape[-1] < mel_frames:
            extra = torch.randn(
                1,
                80,
                mel_frames - self.noise.shape[-1],
                device=self.s3gen.device,
                dtype=self.s3gen.dtype,
            )
            self.noise = torch.cat([self.noise, extra], dim=-1)

        mels = _decode_mels(
            self.s3gen,
            tokens,
            self.ref_dict,
            self.noise[:, :, :mel_frames],
            final,
        )
        wav, source = self.s3gen.hift_inference(mels, self.source)
        self.source = source.detach()
        wav[:, : len(self.s3gen.trim_fade)] *= self.s3gen.trim_fade
        if wav.shape[-1] <= self.emitted:
            return None
        return self._smooth(wav[:, self.emitted :], final)

    def finish(self) -> Any | None:
        import torch

        self.tokens.append(
            torch.full(
                (1, 3),
                self.silence_token,
                device=self.s3gen.device,
                dtype=torch.long,
            )
        )
        return self.flush(final=True)

    def _smooth(self, chunk: Any, final: bool) -> Any | None:
        import torch

        length = chunk.shape[-1]
        if not final and length <= self.crossfade:
            return None
        if final:
            output = self._join(self.tail, chunk) if self.tail is not None else chunk
            self.tail = None
            self.emitted += length
            return output

        body = chunk[:, : length - self.crossfade]
        output = self._join(self.tail, body) if self.tail is not None else body
        self.tail = chunk[:, length - self.crossfade :].detach().clone()
        self.emitted += body.shape[-1]
        return output

    def _join(self, left: Any, right: Any) -> Any:
        import torch

        overlap = min(self.crossfade, left.shape[-1], right.shape[-1])
        fade = torch.linspace(
            0.0, 1.0, overlap, device=right.device, dtype=right.dtype
        ).unsqueeze(0)
        crossed = left[:, -overlap:] * (1.0 - fade) + right[:, :overlap] * fade
        return torch.cat([left[:, :-overlap], crossed, right[:, overlap:]], dim=1)


def _decode_mels(
    s3gen: Any,
    speech_tokens: Any,
    ref_dict: dict[str, Any],
    noise: Any,
    final: bool,
) -> Any:
    """Run the released S3Gen flow with its streaming mask correction locally."""
    import torch
    import torch.nn.functional as F
    from chatterbox.models.s3gen.flow import _repeat_batch_dim
    from chatterbox.models.s3gen.utils.mask import make_pad_mask

    flow = s3gen.flow
    batch = speech_tokens.shape[0]
    values = {
        key: value.to(device=s3gen.device)
        if torch.is_tensor(value)
        else value
        for key, value in ref_dict.items()
    }
    prompt_token = _repeat_batch_dim(values["prompt_token"], batch, 2)
    prompt_token_len = _repeat_batch_dim(values["prompt_token_len"], batch, 1)
    prompt_feat = _repeat_batch_dim(values["prompt_feat"], batch, 3)
    embedding = _repeat_batch_dim(values["embedding"], batch, 2)
    embedding = flow.spk_embed_affine_layer(F.normalize(embedding, dim=1))

    token_len = torch.tensor(
        [speech_tokens.shape[-1]], device=s3gen.device, dtype=torch.long
    )
    tokens = torch.cat([prompt_token, speech_tokens], dim=1)
    token_len = prompt_token_len + token_len
    mask = (~make_pad_mask(token_len)).unsqueeze(-1).to(embedding)
    hidden, hidden_mask = flow.encoder(flow.input_embedding(tokens.long()) * mask, token_len)
    if not final:
        lookahead = flow.pre_lookahead_len * flow.token_mel_ratio
        hidden = hidden[:, :-lookahead]
        hidden_mask = hidden_mask[:, :, :-lookahead]

    hidden_lengths = hidden_mask.sum(dim=-1).squeeze(dim=-1)
    prompt_frames = prompt_feat.shape[1]
    output_frames = hidden.shape[1] - prompt_frames
    hidden = flow.encoder_proj(hidden)
    conditions = torch.zeros(
        batch,
        prompt_frames + output_frames,
        flow.output_size,
        device=s3gen.device,
        dtype=hidden.dtype,
    )
    conditions[:, :prompt_frames] = prompt_feat
    decoder_mask = (~make_pad_mask(hidden_lengths)).unsqueeze(1).to(hidden)
    decoder = flow.decoder
    mu = hidden.transpose(1, 2).contiguous()
    conditions = conditions.transpose(1, 2)
    state = torch.randn_like(mu)
    state[..., mu.shape[-1] - noise.shape[-1] :] = noise
    times = torch.linspace(0, 1, 3, device=mu.device, dtype=mu.dtype)
    dtype = decoder.estimator.dtype
    state, times, mu, decoder_mask, embedding, conditions = [
        value.to(dtype) if value.dtype.is_floating_point else value
        for value in (state, times, mu, decoder_mask, embedding, conditions)
    ]
    for start, end in zip(times[:-1], times[1:]):
        derivative = decoder.estimator(
            state,
            mask=decoder_mask,
            mu=mu,
            t=start[None],
            spks=embedding,
            cond=conditions,
            r=end[None],
        )
        state = state + (end - start) * derivative
    features = state.to(hidden.dtype)
    return features[:, :, prompt_frames:]
