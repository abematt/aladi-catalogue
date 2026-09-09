FROM python:3.12-slim
RUN apt-get update && \
    apt-get install -y --no-install-recommends yaz && \
    rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY app ./app
COPY ./*.py .
COPY run_weekly.sh .
ENV ALADI_BIND=0.0.0.0
EXPOSE 8377
CMD ["python","server.py"]