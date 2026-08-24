FROM python:3.13-slim

RUN pip install flask

COPY app.py /app.py
WORKDIR /

EXPOSE 5000

CMD ["python", "app.py"]
