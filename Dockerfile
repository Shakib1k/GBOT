# বেস ইমেজ: Ubuntu
FROM ubuntu:22.04

# সিস্টেম আপডেট এবং জাভা (Java 17) + পাইথন ইনস্টল
RUN apt-get update && \
    apt-get install -y openjdk-17-jre-headless python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

# ওয়ার্কিং ডিরেক্টরি সেট করা
WORKDIR /app

# ফাইলগুলো কপি করা
COPY requirements.txt .
COPY BOT.py .
COPY dpt-shell-v2.21.1.zip .

# পাইথন লাইব্রেরি ইনস্টল
RUN pip3 install --no-cache-dir -r requirements.txt

# বট রান করা
CMD ["python3", "BOT.py"]
