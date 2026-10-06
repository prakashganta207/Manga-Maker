FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt requirements-ai.txt ./
RUN pip install --no-cache-dir -r requirements.txt
# Optional CLIP consistency scores (CPU torch, ~1 GB). Build with --build-arg WITH_CLIP=1.
ARG WITH_CLIP=0
RUN if [ "$WITH_CLIP" = "1" ]; then pip install --no-cache-dir -r requirements-ai.txt; fi

COPY app ./app
COPY workflows ./workflows
COPY assets ./assets
COPY tests ./tests
COPY pyproject.toml .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
