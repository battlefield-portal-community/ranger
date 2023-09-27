FROM python:3.11-buster as builder
RUN pip install poetry==1.5.1
ENV POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=1 \
    POETRY_VIRTUALENVS_CREATE=1

WORKDIR /venv
RUN apt-get update --yes --quiet && apt-get install --yes --quiet --no-install-recommends git
RUN touch README.md

COPY ["pyproject.toml", "poetry.lock", "./"]
RUN poetry config installer.max-workers 10
RUN poetry install --no-root --no-cache

FROM python:3.11-slim-buster as local

RUN apt-get update && apt-get install libpq5 -y

WORKDIR /app
RUN useradd --create-home ranger

# Set environment variables.
# 1. Force Python stdout and stderr streams to be unbuffered.
ENV VIRTUAL_ENV=/venv/.venv

ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"
COPY --from=builder ${VIRTUAL_ENV} ${VIRTUAL_ENV}

COPY --chown=ranger:ranger ./bot .

RUN chown -R ranger:ranger /app
USER ranger

