# APT Repository for Avalan

Install Avalan from the Avalan PPA on Ubuntu 24.04 LTS (Noble):

```sh
sudo add-apt-repository ppa:avalan-ai/avalan
sudo apt update
sudo apt install avalan
```

Verify the CLI:

```sh
avalan --version
avl --version
```

Supported release: Ubuntu 24.04 LTS (Noble) on `amd64` and `arm64`. Other
Ubuntu releases are out of scope.

## What `apt install avalan` includes

The .deb mirrors the Homebrew formula's default profile. Four upstream
extras are enabled by default and ship with the system package:

- `agent` — multi-agent orchestration helpers.
- `server` — FastAPI server with OpenAI, MCP, and A2A endpoints.
- `tool` — built-in tool implementations.
- `vendors` — bundled third-party SDKs: `aioboto3`, `anthropic`,
  `diffusers`, `google-genai`, `openai`, and Pillow.

Two executables land on `PATH`:

- `/usr/bin/avalan` — main CLI.
- `/usr/bin/avl` — short alias for the same entry point.

Every runtime dependency resolves against Noble's archive or the Avalan
PPA — no `pip install` ever runs as part of `apt install avalan`.

## What `apt install avalan` does NOT include

The default install deliberately leaves out everything heavyweight,
hardware-specific, or otherwise impractical to ship via apt. The
following upstream extras are not in the .deb:

- `browser` — Playwright. No browser binary is fetched at install time.
- `local` — `torch`, `transformers`, `huggingface-hub` for local
  inference.
- `vision` — diffusers visualization stack, OpenCV, `torchvision`.
- `audio` — `soundfile`, `torchaudio`.
- `memory` — vector stores, `tree-sitter`, PDF tooling.
- `mlx` / `apple` — Apple Silicon MLX runtime.
- `nvidia` / `vllm` / `quantization` — CUDA, vLLM, bitsandbytes.
- `code` — RestrictedPython sandbox.
- `youtube` — `youtube-transcript-api`.
- `a2a` — Google's Agent2Agent SDK.
- `litellm` — LiteLLM multi-provider router.
- `ds4` — DualShock 4 input.
- `secrets` — `boto3` + `keyring`.
- `translation` — `protobuf` + `sentencepiece`.

To enable any of them, layer a virtualenv on top of the system install:

```sh
python3 -m venv ~/.avalan/venv
source ~/.avalan/venv/bin/activate
pip install "avalan[browser]"      # or [local], [vision], [audio], ...
```

The system `avalan` and `avl` keep working alongside the venv; the
venv-installed copy shadows them only while activated.

## Further reading

- [`debian/README.Debian`](debian/README.Debian) — runtime notes that
  ship in `/usr/share/doc/avalan/`: how to provide a browser for the
  `browser` extra, the virtualenv layering recipe, and where vendor
  SDKs read their API keys from.
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — host prerequisites and the
  build / lint / test / upload toolchain for working on this
  repository.
