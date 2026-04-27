# Sprint 3 Render and USDZ Tooling

## Local Linux Parity Runner

Run the local Sprint 2 + Sprint 3 acceptance path from the API repo root:

```bash
make sprint3-ci-linux
```

or directly:

```bash
tools/sprint3/run-local-linux-parity.sh
```

The runner is documented in `tools/sprint3/local-linux-parity/README.md`. It builds an Ubuntu-based `linux/amd64` Docker image with Python 3.12, Node 22, Blender 4.5.1, KTX-Software 4.4.2, FFmpeg/ffprobe, and `usd-core==26.5`, then runs `npm ci --prefix tools/sprint2`, `make sprint2-ci`, and `make sprint3-ci` with the repo mounted at `/workspace`.


## CI Fast Profile

`CI_FAST_4K` is the GitHub Actions render profile. It exists to verify the render pipeline and video gates on CPU-only `ubuntu-latest`.

- Blender: 4.5.1 LTS
- Renderer: `BLENDER_WORKBENCH`
- Resolution: 3840x2160
- FPS: 30
- Duration: 60 s
- Camera source: deterministic `camera_path.json`
- Still count: one still per resolved camera segment
- Anti-aliasing: Workbench render AA disabled when the Blender build exposes `scene.display.render_aa`
- Encoder: `ffmpeg` + `libx264`
- Encoder flags: `-preset ultrafast -crf 30 -pix_fmt yuv420p -threads 1`

The dual-render determinism gate compares decoded frame hashes at t=0s, t=30s, and t=58s. The profile avoids Eevee-Next TAA reprojection and dithering jitter by using Workbench still renders plus single-threaded ffmpeg encoding.

## Production GPU Profile

`PRODUCTION_4K_CYCLES_GPU` is documented for the future GPU runner and is not executed in Sprint 3 CI.

```json
{
  "renderer": "CYCLES",
  "device": "GPU",
  "samples": 96,
  "denoiser": "OPENIMAGEDENOISE",
  "max_bounces": 6,
  "diffuse_bounces": 3,
  "glossy_bounces": 3,
  "transparent_max_bounces": 4,
  "color_management": {
    "view_transform": "AgX",
    "look": "Medium High Contrast",
    "exposure": 0.0,
    "gamma": 1.0,
    "display_device": "sRGB"
  }
}
```

## USDZ Tooling

Sprint 3 derives `model.usdz` from Sprint 2 `model.glb`.

- Blender imports the GLB and exports an intermediate USD stage.
- `usd-core==26.5` applies `UsdPreviewSurface` materials and packages the ARKit USDZ.
- KTX-Software 4.4.2 validates Sprint 2 KTX2 textures and provides sampled payload colors.
- The lite USDZ payload caps texture dimensions at 1K; the AR Quick Look hard budget remains <= 8 MB and <= 200,000 triangles.
