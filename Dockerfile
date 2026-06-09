FROM python:3.11-slim

WORKDIR /app

# Copy code and config before installing so the editable install
# picks up the source in /app/ (used by Alembic path resolution).
COPY pyproject.toml .
COPY app/ app/
COPY alembic/ alembic/
COPY alembic.ini .
COPY scripts/ scripts/

# Install the package in editable mode.
# This installs all declared dependencies and adds /app to sys.path via a .pth
# file so that `import app` resolves to the local source tree — required for
# Alembic's __file__-based config path resolution in app/database.py.
RUN pip install --no-cache-dir -e .

# Create the SQLite data directory (mounted as a named volume at runtime)
# and the backups directory.  Set ownership so the non-root user can write.
RUN mkdir -p /data /app/backups \
    && adduser --disabled-password --gecos "" appuser \
    && chown -R appuser:appuser /app /data

USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
