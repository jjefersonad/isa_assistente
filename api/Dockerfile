FROM python:3.12-slim

# libgomp: needed by ctranslate2 (faster-whisper)
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv

WORKDIR /app
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH=/opt/venv/bin:$PATH

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# GPU=1 (docker-compose.gpu.yml): swap onnxruntime for onnxruntime-gpu (Supertonic) and add the CUDA 12 / cuDNN 9
# libraries that ctranslate2 (Whisper) loads. Both fall back to the CPU when the container has no GPU.
ARG GPU=0
RUN if [ "$GPU" = "1" ]; then \
        uv pip uninstall onnxruntime \
        && uv pip install "onnxruntime-gpu[cuda,cudnn]" nvidia-cublas-cu12 "nvidia-cudnn-cu12>=9,<10"; \
    fi
ENV LD_LIBRARY_PATH=/opt/venv/lib/python3.12/site-packages/nvidia/cublas/lib:/opt/venv/lib/python3.12/site-packages/nvidia/cudnn/lib

COPY app.py audio.py ./

# Models live in bind mounts (see docker-compose.yml) so the image stays small.
ENV HF_HOME=/models/hf PIPER_VOICE=/models/piper/pt_BR-faber-medium.onnx SUPERTONIC_CACHE_DIR=/models/supertonic
EXPOSE 8800
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8800"]
