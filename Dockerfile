FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgeos-dev \
    libproj-dev \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/app

# Install the package (and dependencies) after copying source — an editable
# install cannot run before app/ exists.  To cache the dependency layer
# separately, export a requirements file (pip-compile) and install it first.
COPY . .
RUN pip install --no-cache-dir -e ".[dev]"

EXPOSE 8501

CMD ["streamlit", "run", "app/ui/dashboard.py", "--server.port", "8501", "--server.address", "0.0.0.0"]
