#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
IMAGE_NAME="ai-architect-sprint3-parity"
IMAGE_TAG="latest"
PARITY_DIR="$REPO_ROOT/tools/sprint3/local-linux-parity"

build_image() {
    echo "=== Building parity Docker image ==="
    docker build --platform linux/amd64 -t "${IMAGE_NAME}:${IMAGE_TAG}" "$PARITY_DIR"
    echo "=== Image built ==="
}

run_ci() {
    echo "=== Running Sprint 2 + Sprint 3 CI inside parity container ==="
    docker run --platform linux/amd64 --rm \
        -v "$REPO_ROOT:/workspace:cached" \
        -e PYTHONPATH=/workspace \
        -e BLENDER_BIN=/opt/blender/blender \
        -e KTX_BIN=/usr/bin/ktx \
        -e GLTF_TRANSFORM_BIN=/workspace/tools/sprint2/node_modules/.bin/gltf-transform \
        "${IMAGE_NAME}:${IMAGE_TAG}" \
        bash -c '
            set -eo pipefail
            echo "--- Tool versions ---"
            python --version
            node --version
            /opt/blender/blender --background --version 2>&1 || true
            ffmpeg -version 2>&1 || true
            ffprobe -version 2>&1 || true
            ktx --version 2>/dev/null || toktx --version 2>/dev/null || echo "KTX CLI not found"
            echo "--- Python packages ---"
            python -m pip install --break-system-packages -r /workspace/requirements.txt
            python -m pip show usd-core
            echo "--- Node tools ---"
            npm ci --prefix /workspace/tools/sprint2
            echo "=== Sprint 2 CI ==="
            make -C /workspace sprint2-ci
            echo "=== Sprint 3 CI ==="
            make -C /workspace sprint3-ci
            echo "=== Done ==="
        '
}

case "${1:-run}" in
    build)
        build_image
        ;;
    run)
        build_image
        run_ci
        ;;
    run-only)
        run_ci
        ;;
    shell)
        docker run --platform linux/amd64 --rm -it \
            -v "$REPO_ROOT:/workspace:cached" \
            -e PYTHONPATH=/workspace \
            -e BLENDER_BIN=/opt/blender/blender \
            -e KTX_BIN=/usr/bin/ktx \
            "${IMAGE_NAME}:${IMAGE_TAG}" \
            bash
        ;;
    *)
        echo "Usage: $0 {build|run|run-only|shell}" >&2
        exit 1
        ;;
esac
