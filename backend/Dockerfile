# Briefed — AWS Lambda container image (plan §19.15).
#
# One image, two handlers — Terraform's ``image_config.command`` picks:
#   * app.lambda_api.mangum_handler    (API Lambda via Function URL)
#   * app.lambda_worker.sqs_dispatcher (SQS event source)
#   * app.lambda_worker.fanout_handler (EventBridge Scheduler)
#
# SnapStart snapshots the process after module-level init (settings load,
# structlog configure, SSM secret hydration) completes. Warm restores
# skip all of that → ~200–300 ms cold start per ADR 0003.

FROM public.ecr.aws/lambda/python:3.11

# ---- OS build deps ------------------------------------------------------------
# Needed to build native wheels for asyncpg / cryptography.
RUN dnf install -y gcc gcc-c++ libffi-devel openssl-devel \
    && dnf clean all \
    && rm -rf /var/cache/dnf

# ---- Python package install ---------------------------------------------------
# The pyproject is the sole source of deps. We copy the whole project
# (pyproject + readme + license + backend package) and run ``pip install``
# so setuptools can find the ``backend/app`` module layout declared in
# ``[tool.setuptools.packages.find]``. Resulting site-packages hold the
# Briefed code; Lambda discovers the handler from ``image_config.command``.
WORKDIR /build
COPY pyproject.toml README.md LICENSE ./
COPY backend ./backend

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

# ---- Prompt bundles ----------------------------------------------------------
# ``packages/prompts/`` holds the versioned prompt files
# (plan §19.2 monorepo layout). Copy into the Lambda task root so the
# prompt registry can open them without an S3 round-trip.
COPY packages/prompts ${LAMBDA_TASK_ROOT}/packages/prompts

# ---- Runtime env --------------------------------------------------------------
ENV BRIEFED_RUNTIME=lambda-api \
    PYTHONUNBUFFERED=1

# Default handler (API). Terraform modules override for the worker +
# fanout Lambdas via ``image_config.command``. The Briefed package lives
# in site-packages after ``pip install``, so ``app.lambda_api.*`` resolves.
CMD ["app.lambda_api.mangum_handler"]
