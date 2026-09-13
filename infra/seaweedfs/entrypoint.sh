#!/bin/sh
# Renders the S3 identity file from the environment, then starts the all-in-one
# SeaweedFS server (master + volume + filer + S3 gateway).
#
# Credentials never land in git: they come from .env through the container env.
set -eu

: "${STORAGE_ACCESS_KEY:?STORAGE_ACCESS_KEY is required}"
: "${STORAGE_SECRET_KEY:?STORAGE_SECRET_KEY is required}"

S3_CONFIG=/etc/seaweedfs/s3.json
mkdir -p "$(dirname "${S3_CONFIG}")"

cat > "${S3_CONFIG}" <<JSON
{
  "identities": [
    {
      "name": "app",
      "credentials": [
        {
          "accessKey": "${STORAGE_ACCESS_KEY}",
          "secretKey": "${STORAGE_SECRET_KEY}"
        }
      ],
      "actions": ["Admin", "Read", "Write", "List", "Tagging"]
    }
  ]
}
JSON
chmod 600 "${S3_CONFIG}"

# No "anonymous" identity on purpose: public read is granted per bucket by the
# bucket policies the app applies on startup (app/core/services/storage/policy.py).
exec weed server \
  -dir=/data \
  -ip=seaweedfs \
  -ip.bind=0.0.0.0 \
  -master.volumeSizeLimitMB="${SEAWEEDFS_VOLUME_SIZE_LIMIT_MB:-1024}" \
  -volume.max=0 \
  -volume.index=leveldb \
  -filer \
  -s3 \
  -s3.port="${SEAWEEDFS_S3_PORT:-8333}" \
  -s3.config="${S3_CONFIG}" \
  -s3.allowedOrigins="${SEAWEEDFS_CORS_ORIGINS:-*}" \
  -metricsPort="${SEAWEEDFS_METRICS_PORT:-9324}" \
  "$@"
