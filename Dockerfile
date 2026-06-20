FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md setup.py ./
COPY src ./src

RUN pip install --no-cache-dir .

CMD ["ecoflow-mqtt"]
