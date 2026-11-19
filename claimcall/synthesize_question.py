"""Synthesize the caller question without loading native speech libraries in the parent."""
import argparse
import wave


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--voice", required=True)
    parser.add_argument("--text", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    from piper import PiperVoice

    voice = PiperVoice.load(args.voice)
    with wave.open(args.output, "wb") as wav:
        voice.synthesize_wav(args.text, wav)


if __name__ == "__main__":
    main()
