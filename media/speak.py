#!/usr/bin/env python3
"""Read text aloud with Kokoro. Runs with Kokoro's own Python, inside media_wall.sh.

    speak.py <text file> <out.wav> <model.onnx> <voices.bin> <voice> <speed> <language>

The voice is a name, or a blend of several: `af_heart=0.25+am_david=0.75`.

The text is read in pieces of a few sentences, since the model takes a limited
number of sounds at a time, with a pause between paragraphs. Writes 16-bit mono WAV.
"""

import re
import sys
import wave

import numpy as np
from kokoro_onnx import Kokoro

PIECE = 350          # characters per piece; Kokoro takes at most about 510 sounds
PAUSE = 0.35         # seconds of silence between paragraphs


def pieces(paragraph):
    sentences = re.split(r"(?<=[.!?…])\s+", paragraph.strip())
    piece = ""
    for sentence in sentences:
        while len(sentence) > PIECE:  # a sentence too long on its own, cut at a comma or a space
            cut = max(sentence.rfind(",", 0, PIECE), sentence.rfind(" ", 0, PIECE))
            cut = cut if cut > 0 else PIECE
            if piece:
                yield piece
                piece = ""
            yield sentence[:cut + 1].strip()
            sentence = sentence[cut + 1:].strip()
        if piece and len(piece) + len(sentence) + 1 > PIECE:
            yield piece
            piece = ""
        piece = f"{piece} {sentence}".strip()
    if piece:
        yield piece


def style(kokoro, voice):
    """A voice: its name, or a blend, `af_heart=0.25+am_david=0.75`, the voices' styles mixed in
    those shares (Kokoro takes a mixed style in place of a name)."""
    if "=" not in voice:
        return voice
    return sum(kokoro.get_voice_style(name) * float(share)
               for name, _, share in (part.partition("=") for part in voice.split("+")))


def main(argv):
    text_file, out_wav, model, voices, voice, speed, language = argv[1:8]
    kokoro = Kokoro(model, voices)
    voice = style(kokoro, voice)
    with open(text_file, encoding="utf-8") as f:
        paragraphs = [p for p in re.split(r"\n\s*\n", f.read()) if p.strip()]
    audio, rate = [], 24000
    for paragraph in paragraphs:
        for piece in pieces(paragraph):
            samples, rate = kokoro.create(piece, voice=voice, speed=float(speed), lang=language)
            audio.append(np.asarray(samples, dtype=np.float32))
        audio.append(np.zeros(int(rate * PAUSE), dtype=np.float32))
    if not audio:
        sys.exit("speak: no text to read")
    joined = np.clip(np.concatenate(audio), -1.0, 1.0)
    with wave.open(out_wav, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes((joined * 32767).astype(np.int16).tobytes())
    print(f"{len(joined) / rate:.1f} seconds")


if __name__ == "__main__":
    main(sys.argv)
