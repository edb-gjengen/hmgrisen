FROM python:3.12

WORKDIR /app

COPY requirements.txt .

RUN python3 -m pip install --no-cache-dir -r requirements.txt

COPY . .

CMD [ "uvicorn", "src.server:app", "--host", "0.0.0.0", "--port", "8001" ]
