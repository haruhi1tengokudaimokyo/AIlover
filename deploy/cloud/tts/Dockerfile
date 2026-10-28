FROM pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime
RUN apt-get update && apt-get install -y --no-install-recommends git gcc g++ cmake ffmpeg libsox-dev && rm -rf /var/lib/apt/lists/*
RUN git clone https://github.com/RVC-Boss/GPT-SoVITS.git /app/gsv && cd /app/gsv && git checkout b4570b876f5c086819ba84e3215472733c6a7b70
COPY constraints.txt /app/constraints.txt
COPY training-environment.lock.txt /app/training-environment.lock.txt
RUN pip install --no-cache-dir -c /app/constraints.txt -c /app/training-environment.lock.txt -r /app/gsv/requirements.txt runpod==1.7.13
ENV PYTHONPATH=/app/gsv:/app/gsv/GPT_SoVITS PYTHONUNBUFFERED=1
WORKDIR /app/gsv
COPY worker.py /app/worker.py
COPY bootstrap.py /app/bootstrap.py
CMD ["python", "/app/worker.py"]
