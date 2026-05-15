````md
## Cloudflare R2 Environment Variables

Create a `.env` file in the project root and add the following variables:

```env
R2_ACCOUNT_ID=your_cloudflare_account_id
R2_ACCESS_KEY_ID=your_r2_access_key_id
R2_SECRET_ACCESS_KEY=your_r2_secret_access_key
R2_BUCKET_NAME=your_bucket_name
````

### Optional Variables

```env
# Custom R2 endpoint
R2_ENDPOINT_URL=https://<account_id>.r2.cloudflarestorage.com

# Public base URL (R2 public URL or custom CDN domain)
R2_PUBLIC_BASE_URL=https://cdn.example.com

# Optional folder/prefix inside bucket
R2_PREFIX=images

# Cache-Control header for uploaded files
R2_CACHE_CONTROL=public, max-age=31536000

# Optional custom metadata
R2_METADATA_WEBSITE=https://example.com
```

---

## Example `.env`

```env
R2_ACCOUNT_ID=xxxxxxxxxxxxxxxxxxxx
R2_ACCESS_KEY_ID=xxxxxxxxxxxxxxxxxxxx
R2_SECRET_ACCESS_KEY=xxxxxxxxxxxxxxxxxxxx
R2_BUCKET_NAME=my-images-bucket

R2_PUBLIC_BASE_URL=https://cdn.example.com
R2_PREFIX=uploads
R2_CACHE_CONTROL=public, max-age=31536000
R2_METADATA_WEBSITE=https://example.com
```

---

## Example Usage

Upload and test an image:

```bash
python r2_image_test.py static/logo.png
```

Generate a presigned URL and download test:

```bash
python r2_image_test.py static/logo.png --presign --download-dir ./r2-downloads
```

```
```
