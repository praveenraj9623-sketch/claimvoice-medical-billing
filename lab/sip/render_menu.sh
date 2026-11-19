#!/bin/sh
# Render the same simulated insurer prompts for preflight and Asterisk playback.
set -eu
case "$1" in
  2) digit=two ;;
  3) digit=three ;;
  *) echo "Unknown lab menu digit: $1" >&2; exit 2 ;;
esac
phrase="To check the status of your claim. Please press the number $digit."
case "$2" in
  *.wav) format=wav ;;
  *.ulaw) format=mulaw ;;
  *) echo "Expected a .wav or .ulaw output" >&2; exit 2 ;;
esac
exec ffmpeg -v error -nostdin -f lavfi -i "flite=text='$phrase':voice=rms" \
  -ar 8000 -ac 1 -c:a pcm_mulaw -f "$format" "$2"
