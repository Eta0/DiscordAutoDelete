FROM python:alpine

RUN apk add sqlite-dev

WORKDIR /bot
COPY ./ /bot

RUN python -m pip install -e .[speed]

CMD ["python", "-m", "discord_autodelete"]
