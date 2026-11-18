# ClaimCall · CPU voice feasibility

This branch tests whether the proposed speech stack can handle a short insurer reply on the target computer. Run it before starting the SIP and dashboard stages.

## Run on Ubuntu or WSL2

Use a Linux terminal in the repository root. Install Git, FFmpeg with flite, Python 3.11 or 3.12 with venv, curl, and a CPU build of [llama.cpp](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md) providing `llama-server` on PATH.

For example, to build the server with Ubuntu's compiler and CMake, run the following in WSL. Use a fresh checkout path. The output of the version command identifies the build used for the trial.

```bash
sudo apt-get update
sudo apt-get install -y build-essential cmake git ffmpeg curl python3-venv libcurl4-openssl-dev libssl-dev
git clone --depth 1 https://github.com/ggml-org/llama.cpp.git ~/claimcall-llama
cmake -S ~/claimcall-llama -B ~/claimcall-llama/build -DCMAKE_BUILD_TYPE=Release
cmake --build ~/claimcall-llama/build --target llama-server -j 4
export PATH="$HOME/claimcall-llama/build/bin:$PATH"
llama-server --version
```

Then run from the ClaimVoice checkout on `claimcall-rebuild`:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-voice-probe.txt
bash scripts/run_voice_probe.sh
```

The first run needs internet access and several GB of disk for the public Qwen, Whisper and Piper files. The script starts its own loopback-only llama.cpp server, waits for readiness, and stops it on exit. The model server alias is `claimcall`. Review the [Lessac voice model card](https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/lessac/medium/MODEL_CARD) before distributing that voice. Generated output stays under `artifacts/voice/`.

## Read the result

Two invented representatives report a paid claim and a pending claim. FFmpeg speaks each fixture with flite and encodes it as mono G.711 µ-law at 8 kHz. Faster-whisper transcribes the encoded file. Qwen receives only the transcript and uses a structured tool to capture the fields. The probe validates the tool response, checks against the fixture, and uses Piper to speak a confirmation based on what the model actually captured.

Open `result.json` and listen to `reply.wav` for each case. A pass requires exact capture of the expected fields, unknown payment values for the pending case, and non-silent output audio. A failed stage or field mismatch makes the command exit unsuccessfully. Inspect the incoming WAV, transcript and captured fields to locate errors.

Timing covers file transcription, the model request (including any validation retry), and whole-file speech generation. These figures measure batch processing on this computer. First audible response latency requires the streaming SIP integration. Keep the first run and a repeat run for comparison. These two fixed voices/utterances establish feasibility only; the human microphone test and the three complete call acceptance scenarios still require separate runs.

For a reported paid claim, listen to the reference clarification as well. The caller asks the representative to identify each digit by position. The probe accepts two consecutive matching readings, allows at most two clarification turns, and leaves the reference unknown for review when it cannot confirm it. Compare `initial_capture`, `reference_turns` and `captured` in the result. The new reference-check time includes synthetic fixture generation. The representative's answers are scripted for this batch test. Both the reference prompts and replies are saved as WAV files.
