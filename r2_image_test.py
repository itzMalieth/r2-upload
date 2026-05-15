from __future__ import annotations

import argparse
import hashlib
import logging
import mimetypes
import os
import posixpath
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


LOGGER = logging.getLogger("r2-image-test")
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}
IMAGE_CONTENT_TYPES = {
    ".avif": "image/avif",
    ".gif": "image/gif",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
DEFAULT_PRESIGN_SECONDS = 900


@dataclass(frozen=True)
class R2Config:
    account_id: str
    access_key_id: str
    secret_access_key: str
    bucket_name: str
    endpoint_url: str
    public_base_url: str | None = None
    key_prefix: str = ""
    cache_control: str = "public, max-age=31536000"
    metadata_website: str = ""

    @classmethod
    def from_env(cls) -> "R2Config":
        load_dotenv()

        account_id = _required_env("R2_ACCOUNT_ID")
        endpoint_url = os.getenv(
            "R2_ENDPOINT_URL",
            f"https://{account_id}.r2.cloudflarestorage.com",
        ).rstrip("/")

        return cls(
            account_id=account_id,
            access_key_id=_required_env("R2_ACCESS_KEY_ID"),
            secret_access_key=_required_env("R2_SECRET_ACCESS_KEY"),
            bucket_name=_required_env("R2_BUCKET_NAME"),
            endpoint_url=endpoint_url,
            public_base_url=_optional_url("R2_PUBLIC_BASE_URL"),
            key_prefix=os.getenv("R2_PREFIX", "").strip().strip("/"),
            cache_control=os.getenv(
                "R2_CACHE_CONTROL",
                "public, max-age=31536000",
            ).strip(),
            metadata_website=os.getenv("R2_METADATA_WEBSITE", "").strip(),
        )


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _optional_url(name: str) -> str | None:
    value = os.getenv(name, "").strip().rstrip("/")
    return value or None


def create_r2_client(config: R2Config):
    import boto3
    from botocore.client import Config

    return boto3.client(
        "s3",
        endpoint_url=config.endpoint_url,
        aws_access_key_id=config.access_key_id,
        aws_secret_access_key=config.secret_access_key,
        region_name="auto",
        config=Config(
            signature_version="s3v4",
            retries={"max_attempts": 5, "mode": "standard"},
            s3={"addressing_style": "path"},
            connect_timeout=10,
            read_timeout=60,
        ),
    )


def validate_image_path(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"Image does not exist: {path}")
    if path.suffix.lower() not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise ValueError(f"Unsupported image extension '{path.suffix}'. Allowed: {allowed}")
    if path.stat().st_size <= 0:
        raise ValueError(f"Image is empty: {path}")


def content_type_for(path: Path) -> str:
    fallback_content_type = IMAGE_CONTENT_TYPES.get(path.suffix.lower())
    content_type, _ = mimetypes.guess_type(path.name)
    content_type = content_type or fallback_content_type
    if not content_type or not content_type.startswith("image/"):
        raise ValueError(f"Could not detect an image content type for: {path}")
    return content_type


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_object_key(image_path: Path, explicit_key: str | None, prefix: str) -> str:
    if explicit_key:
        key = explicit_key.strip().replace("\\", "/").lstrip("/")
    else:
        key = image_path.name

    if prefix and not key.startswith(f"{prefix}/"):
        key = posixpath.join(prefix, key)

    key = posixpath.normpath(key).lstrip("/")
    key_parts = [part for part in key.split("/") if part]
    if not key_parts or any(part == ".." for part in key_parts):
        raise ValueError(f"Invalid R2 object key: {key!r}")
    return "/".join(key_parts)


def object_exists(s3_client, bucket_name: str, key: str) -> bool:
    from botocore.exceptions import ClientError

    try:
        s3_client.head_object(Bucket=bucket_name, Key=key)
        return True
    except ClientError as exc:
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        code = exc.response.get("Error", {}).get("Code")
        if status == 404 or code in {"404", "NoSuchKey", "NotFound"}:
            return False
        raise


def upload_image(
    s3_client,
    config: R2Config,
    image_path: Path,
    key: str,
    content_type: str,
    sha256_hash: str,
) -> None:
    metadata = {
        "app": "r2-image-uploader",
        "asset-type": "website-image",
        "original-filename": image_path.name,
        "sha256": sha256_hash,
        "source": "r2_image_test.py",
    }

    if config.metadata_website:
        metadata["website"] = config.metadata_website

    extra_args = {
        "ContentType": content_type,
        "ContentDisposition": f'inline; filename="{image_path.name}"',
        "Metadata": metadata,
    }

    if config.cache_control:
        extra_args["CacheControl"] = config.cache_control

    s3_client.upload_file(
        str(image_path),
        config.bucket_name,
        key,
        ExtraArgs=extra_args,
    )


def download_image(s3_client, bucket_name: str, key: str, download_dir: Path) -> Path:
    download_dir.mkdir(parents=True, exist_ok=True)
    destination = download_dir / Path(key).name
    s3_client.download_file(bucket_name, key, str(destination))
    return destination


def public_url(config: R2Config, key: str) -> str | None:
    if not config.public_base_url:
        return None
    return f"{config.public_base_url}/{key}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Upload an image to Cloudflare R2, download it back, and verify it.",
    )
    parser.add_argument("image", type=Path, help="Local image file to upload.")
    parser.add_argument("--key", help="Object key to use in R2. Defaults to image filename.")
    parser.add_argument(
        "--download-dir",
        type=Path,
        default=Path("r2-downloads"),
        help="Directory for the downloaded verification copy.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow replacing an existing object with the same key.",
    )
    parser.add_argument(
        "--delete-after-test",
        action="store_true",
        help="Delete the uploaded object after verification.",
    )
    parser.add_argument(
        "--presign",
        action="store_true",
        help="Use a temporary GET URL when no public base URL is configured.",
    )
    parser.add_argument(
        "--presign-seconds",
        type=int,
        default=DEFAULT_PRESIGN_SECONDS,
        help=f"Presigned URL lifetime in seconds. Default: {DEFAULT_PRESIGN_SECONDS}.",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    parser.add_argument(
        "--details",
        action="store_true",
        help="Print bucket, key, hash, and downloaded file path after the final URL.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(message)s",
    )

    try:
        image_path = args.image.resolve()
        validate_image_path(image_path)
        content_type = content_type_for(image_path)
        source_hash = sha256_file(image_path)

        config = R2Config.from_env()
        s3_client = create_r2_client(config)
        key = build_object_key(image_path, args.key, config.key_prefix)

        if object_exists(s3_client, config.bucket_name, key) and not args.overwrite:
            raise RuntimeError(
                f"Object already exists: s3://{config.bucket_name}/{key}. "
                "Use --overwrite or choose another --key."
            )

        LOGGER.info("Uploading %s to r2://%s/%s", image_path, config.bucket_name, key)

        upload_image(
            s3_client,
            config,
            image_path,
            key,
            content_type,
            source_hash,
        )

        head = s3_client.head_object(Bucket=config.bucket_name, Key=key)
        remote_size = int(head.get("ContentLength", -1))

        if remote_size != image_path.stat().st_size:
            raise RuntimeError(
                f"Uploaded size mismatch: local={image_path.stat().st_size}, remote={remote_size}"
            )

        downloaded_path = download_image(
            s3_client,
            config.bucket_name,
            key,
            args.download_dir.resolve(),
        )

        downloaded_hash = sha256_file(downloaded_path)

        if downloaded_hash != source_hash:
            raise RuntimeError(
                f"Downloaded SHA-256 mismatch: local={source_hash}, downloaded={downloaded_hash}"
            )

        url = public_url(config, key)

        if not url and args.presign:
            url = s3_client.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": config.bucket_name,
                    "Key": key,
                },
                ExpiresIn=args.presign_seconds,
            )

        if not url:
            raise RuntimeError(
                "Upload verified, but no public URL is configured. "
                "Set R2_PUBLIC_BASE_URL to your r2.dev URL or custom domain."
            )

        LOGGER.info("Upload and retrieval verified")

        print(url)

        if args.details:
            print(f"bucket={config.bucket_name}")
            print(f"key={key}")
            print(f"content_type={content_type}")
            print(f"sha256={source_hash}")
            print(f"downloaded={downloaded_path}")

        if args.delete_after_test:
            s3_client.delete_object(
                Bucket=config.bucket_name,
                Key=key,
            )
            LOGGER.info("Deleted test object r2://%s/%s", config.bucket_name, key)

        return 0

    except ModuleNotFoundError as exc:
        if exc.name in {"boto3", "botocore"}:
            LOGGER.error(
                "Missing dependency '%s'. Run: pip install -r requirements.txt",
                exc.name,
            )
        else:
            LOGGER.error("%s", exc)
        return 1

    except Exception as exc:
        LOGGER.error("%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
