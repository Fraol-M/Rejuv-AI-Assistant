# Use the official Python 3.10 slim image as the base image
FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1
ENV POETRY_HTTP_TIMEOUT=600
ENV PIP_DEFAULT_TIMEOUT=180
ENV PIP_RETRIES=10

# Set the working directory
WORKDIR /AI-Assistant


# Create log directory here
RUN mkdir -p /AI-Assistant/logfiles

# Install Poetry
RUN pip install --no-cache-dir poetry

# Copy the application code
COPY . /AI-Assistant

# Install dependencies 
RUN poetry config virtualenvs.create false && \
    for i in 1 2 3; do \
      if poetry install --no-root --no-interaction; then \
        break; \
      fi; \
      if [ "$i" -eq 3 ]; then \
        echo "poetry install failed after 3 attempts"; \
        exit 1; \
      fi; \
      echo "poetry install failed (attempt $i), retrying in 20s..."; \
      sleep 20; \
    done && \
    python -m pip install --no-cache-dir gunicorn e2b-code-interpreter

# Run the application
CMD ["gunicorn", "-w", "4", "--bind", "0.0.0.0:$FLASK_PORT", "run:app"]
