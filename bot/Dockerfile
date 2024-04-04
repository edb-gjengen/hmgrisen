FROM python:3.12

WORKDIR /app

COPY requirements.txt .

RUN apt-get update && apt-get install -y pandoc

RUN python3 -m pip install --no-cache-dir -r requirements.txt

COPY . .

VOLUME logs

CMD ["python3", "src/run.py"]
