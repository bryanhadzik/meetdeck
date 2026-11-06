FROM eclipse-temurin:21-jdk AS mmdb
WORKDIR /mmdb
COPY mmdb/lib/ lib/
COPY mmdb/Builder.java mmdb/Dump.java mmdb/Svc.java mmdb/profile.json ./
RUN javac -cp "lib/*" Builder.java Dump.java Svc.java

FROM python:3.12-slim
COPY --from=eclipse-temurin:21-jre /opt/java/openjdk /opt/java/openjdk
ENV JAVA_HOME=/opt/java/openjdk PATH="/opt/java/openjdk/bin:${PATH}"
COPY --from=mmdb /mmdb/lib/ /opt/mmdb/lib/
COPY --from=mmdb /mmdb/*.class /mmdb/profile.json /opt/mmdb/
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends fonts-crosextra-caladea && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir fastapi==0.115.* uvicorn==0.32.* python-multipart==0.0.* reportlab==4.2.* tzdata pypdf==5.*
COPY app/ /app/
COPY timing/ /app/timing/
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
