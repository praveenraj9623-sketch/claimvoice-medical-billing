#!/bin/sh
# Render the same simulated insurer prompts for preflight and Asterisk playback.
set -eu
case "$1" in
  2) phrase="For claim status press two"; voice=slt ;;
  3) phrase="For claim status. Please press the number three."; voice=rms ;;
  *) echo "Unknown lab menu digit: $1" >&2; exit 2 ;;
esac
case "$2" in
  *.wav) format=wav ;;
  *.ulaw) format=mulaw ;;
  *) echo "Expected a .wav or .ulaw output" >&2; exit 2 ;;
esac
exec ffmpeg -v error -nostdin -f lavfi -i "flite=text='$phrase':voice=$voice" \
  -ar 8000 -ac 1 -c:a pcm_mulaw -f "$format" "$2"
