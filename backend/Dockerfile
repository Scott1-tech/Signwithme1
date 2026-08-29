FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# pdfplumber/pypdf need no system libs, but Pillow and reportlab want these.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libjpeg62-turbo-dev zlib1g-dev libfreetype6-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
