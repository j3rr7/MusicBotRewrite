FROM python:3.12.8-alpine3.21

WORKDIR /app

RUN apk add --no-cache libffi-dev libsodium-dev python3-dev git

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]