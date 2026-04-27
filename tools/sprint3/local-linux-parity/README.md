# Sprint 3 Local Linux Parity Runner

This runner replaces GitHub Actions as the Sprint 3 verification transport for local acceptance evidence.

## Host command

Run from the API repo root:

```bash
tools/sprint3/run-local-linux-parity.sh
```

Equivalent Make target:

```bash
make sprint3-ci-linux
```

The script builds a `linux/amd64` Docker image and mounts the API repo at `/workspace`, so generated artifacts remain available on the host under:

```text
storage/professional-deliverables/project-golden-townhouse/
```

## Toolchain

The image installs:

- Ubuntu 24.04 base image
- Python 3.12
- Node 22
- Blender 4.5.1 Linux x64 at `/opt/blender/blender`
- KTX-Software 4.4.2
- FFmpeg and ffprobe from Ubuntu packages
- Python dependencies from `requirements.txt`, including `usd-core==26.5`
- Sprint 2 Node tools with `npm ci --prefix tools/sprint2`

## Commands run inside the container

```bash
python --version
node --version
/opt/blender/blender --background --version
ffmpeg -version
ffprobe -version
ktx --version || toktx --version
python -m pip show usd-core
npm ci --prefix tools/sprint2
make sprint2-ci
make sprint3-ci
```

## Expected outputs

Sprint 2:

```text
storage/professional-deliverables/project-golden-townhouse/3d/model.glb
storage/professional-deliverables/project-golden-townhouse/3d/model.fbx
storage/professional-deliverables/project-golden-townhouse/textures/*.ktx2
```

Sprint 3:

```text
storage/professional-deliverables/project-golden-townhouse/3d/model.usdz
storage/professional-deliverables/project-golden-townhouse/3d/model_lite.usdz
storage/professional-deliverables/project-golden-townhouse/video/master_4k.mp4
storage/professional-deliverables/project-golden-townhouse/video/camera_path.json
storage/professional-deliverables/project-golden-townhouse/sprint3_gate_summary.json
storage/professional-deliverables/project-golden-townhouse/sprint3_gate_summary.md
```

On Apple Silicon hosts this runs with `--platform linux/amd64`; emulation can be slow, especially for Blender video rendering. If build/download/runtime becomes infeasible, report `BLOCKED` with the exact command and error.
