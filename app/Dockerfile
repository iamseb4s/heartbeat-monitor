# Use an official Python runtime as a parent image
FROM python:3.14-alpine

# Set the working directory in the container
WORKDIR /app

# Copy the dependencies file to the working directory
COPY requirements.txt .

# Install build dependencies for psutil and other potential packages, then install Python packages
# Finally, remove build dependencies to keep the image size small
RUN apk add --no-cache gcc python3-dev musl-dev linux-headers && \
    pip install --no-cache-dir --trusted-host pypi.python.org -r requirements.txt && \
    apk del gcc python3-dev musl-dev linux-headers

# Copy the content of the current directory into the container at /app
COPY . .

# Specify the command to run on container start
CMD ["python", "monitor.py"]
