FROM python:3.13-slim

RUN pip install flask
RUN mkdir -p /data

COPY app.py /app.py
WORKDIR /

EXPOSE 5001

CMD ["python", "app.py"]
