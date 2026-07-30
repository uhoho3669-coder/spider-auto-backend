FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir flask

COPY . .

# Run the web service on container startup
CMD ["python", "app.py"]
