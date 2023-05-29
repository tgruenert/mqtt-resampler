# Base image
FROM python:3.9-slim

# Set working directory
WORKDIR /app

# Copy requirements.txt
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the code
COPY main.py .

# Define the volume mount for config.yaml
VOLUME ["/app/config.yaml"]

# Run the application
CMD ["python", "main.py"]
