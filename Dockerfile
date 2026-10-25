FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    YOLO_CONFIG_DIR=/data/model-cache

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --index-url https://pypi.org/simple \
        --extra-index-url https://download.pytorch.org/whl/cpu \
        torch torchvision \
    && pip install --no-cache-dir -r requirements.txt \
    && pip uninstall -y opencv-python opencv-python-headless \
    && pip install --no-cache-dir --no-deps opencv-python-headless

COPY watcher.py .

RUN python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')" \
    && chmod 755 /app \
    && chmod 644 /app/watcher.py /app/yolov8n.pt

CMD ["python", "watcher.py"]
