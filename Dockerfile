FROM python:3.12-slim

# GDAL/PROJ system libraries needed by rasterio, geopandas, fiona
RUN apt-get update && apt-get install -y --no-install-recommends \
    gdal-bin \
    libgdal-dev \
    libgeos-dev \
    libproj-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

ENV GDAL_CONFIG=/usr/bin/gdal-config

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

# Render (and most hosts) inject $PORT at runtime; default to 5000 for local docker run
ENV PORT=5000
EXPOSE 5000

# 2 workers is plenty for a dissertation-scale demo; --timeout 120 because
# kriging on dense point sets can take a while
CMD gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120
