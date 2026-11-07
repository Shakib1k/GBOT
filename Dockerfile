FROM ubuntu:22.04

RUN apt-get update && \
    apt-get install -y openjdk-17-jre-headless python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python3", "BOT.py"]
