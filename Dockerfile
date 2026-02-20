FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgdal-dev \
    libgeos-dev \
    libproj-dev \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/app

COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]"

COPY . .

RUN pip install --no-cache-dir -e ".[dev]"

EXPOSE 8501

CMD ["streamlit", "run", "app/ui/dashboard.py", "--server.port", "8501", "--server.address", "0.0.0.0"]
