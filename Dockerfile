# syntax=docker/dockerfile:1.2

## What's this?
# This Dockerfile creates a container image containing
# Python, Discord Autodelete's dependencies,
# and a zipapp of Discord Autodelete itself.

## Do I need this?
# This is *not* required to run Discord Autodelete;
# it is just another way of doing so, for people who like containers.

## Notes for building
# This image must be built with BuildKit features available, e.g.
# by running `DOCKER_BUILDKIT=1 docker build .` in the source root.

## Notes for running (IMPORTANT)
# The resulting container MUST be run attached to persistent storage
# of some type, specifying the --database path accordingly.
# All autodelete configurations are stored in the --database file,
# so if it is lost, the bot's settings on all servers will vanish too.

FROM python:3.11.3-alpine3.18
RUN apk add --no-cache sqlite

WORKDIR /tmp/install
# Install dependencies and create a pre-compiled zipapp
RUN --mount=type=bind,target=.,rw \
    # Modifications to this directory are ephemeral.
    # Don't leave traces of bytecode compiled during this step
    # due to python -m ... invocations, but newly installed packages
    # can keep any deliberately pre-compiled bytecode.
    export PYTHONDONTWRITEBYTECODE=1 && \
    # Install dependencies n' such
    python -m pip install --no-cache-dir .[speed] && \
    # pip's cache can be a little stubborn
    python -m pip cache purge && \
    # Only .py files are needed for the rest of the install
    find -type f ! -iname *.py -delete && \
    # Pre-compile (zipapps are hard to add __pycache__ to later)
    python -m compileall discord_autodelete && \
    # Zip the entire directory to end up with a folder structure like
    # ./discord_autodelete.zip/discord_autodelete/__init__.py
    python -m zipfile -c ./discord_autodelete.zip discord_autodelete && \
    # Install the finished zip
    mkdir /app && cp ./discord_autodelete.zip /app/discord_autodelete.zip
WORKDIR /app

# Add discord_autodelete to the Python modules path for "-m" execution
ENV PYTHONPATH="/app/discord_autodelete.zip${PYTHONPATH:+:$PYTHONPATH}"

# Set this to disable all runtime Python bytecode file generation in the
# resulting image, slightly reducing performance, but also significantly
# reducing each container's disk usage footprint.
ARG NO_BYTECODE=""
ENV PYTHONDONTWRITEBYTECODE="{$NO_BYTECODE:+1}"

# --cwd-env is necessary for load_dotenv not to break from running as a zipapp
ENTRYPOINT ["python", "-m", "discord_autodelete", "--cwd-env"]
