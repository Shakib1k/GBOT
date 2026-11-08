# বেস ইমেজ: Java 17 এবং Python 3
FROM eclipse-temurin:17-jdk-jammy

# Python এবং pip ইনস্টল করা
RUN apt-get update && apt-get install -y python3 python3-pip

# ওয়ার্কিং ডিরেক্টরি সেট করা
WORKDIR /app

# ফাইলগুলো কপি করা
COPY requirements.txt .
COPY BOT.py .
COPY dpt-shell-v2.21.1.zip .

# পাইথন লাইব্রেরি ইনস্টল
RUN pip3 install -r requirements.txt

# বট রান করা
CMD ["python3", "BOT.py"]
