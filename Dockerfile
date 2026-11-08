# বেস ইমেজ: Ubuntu (জাভা এবং পাইথন দুটোই সহজে ইনস্টল করা যায়)
FROM ubuntu:22.04

# সিস্টেম আপডেট এবং জাভা (Java 17) + পাইথন ইনস্টল করা
RUN apt-get update && \
    apt-get install -y openjdk-17-jre-headless python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

# ওয়ার্কিং ডিরেক্টরি সেট করা
WORKDIR /app

# রিকোয়ারমেন্ট ফাইল কপি করা
COPY requirements.txt .

# পাইথন লাইব্রেরি ইনস্টল করা
RUN pip3 install --no-cache-dir -r requirements.txt

# প্রজেক্টের সব ফাইল (BOT.py, admin.html, dpt-shell-v2.21.1.zip, protection.zip) কপি করা
COPY . .

# পোর্ট এক্সপোজ করা (Render-এর জন্য জরুরি)
EXPOSE 8080

# বট এবং ফ্লাস্ক সার্ভার রান করা
CMD ["python3", "BOT.py"]
