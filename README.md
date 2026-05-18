# APT Repository for Avalan

Install Avalan with apt:

```sh
sudo add-apt-repository ppa:avalan-ai/avalan
sudo apt update
sudo apt install avalan
```

Verify the CLI:

```sh
avalan --version
```

Supported release: Ubuntu 24.04 LTS (Noble) on `amd64` and `arm64`.

## What this installs

This installs the Avalan CLI as a Debian package on Ubuntu.

The default APT package mirrors the Homebrew formula's default profile (`agent`, `server`, `tool`, `vendors`) and intentionally avoids installing every optional Python extra. Hardware-specific and heavyweight extras such as `mlx`, `apple`, `nvidia`, `vllm`, `audio`, `vision`, and `quantization` should be packaged separately or installed with pip when needed.
