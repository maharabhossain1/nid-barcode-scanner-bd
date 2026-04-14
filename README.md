# NID Barcode Reader

A FastAPI microservice that decodes **PDF417 barcodes from Bangladesh National ID (NID) cards** — both the older Machine Readable Zone (MRZ) format and the newer Digital NID (XML) format.

Runs entirely in-memory. No files written to disk, no database, no storage dependencies. Drop it behind any API gateway and call it.

---

## Contents

- [How It Works](#how-it-works)
- [Supported NID Formats](#supported-nid-formats)
- [Quick Start](#quick-start)
- [Docker](#docker)
- [API Reference](#api-reference)
- [Configuration](#configuration)
- [Rate Limiting](#rate-limiting)
- [Project Structure](#project-structure)
- [Contributing](#contributing)

---

## How It Works

```
Upload → Validate → detect_barcode_region() → smart_preprocess() → parallel decode → parse → respond
```

1. **Region detection** — morphological edge detection + horizontal projection to isolate the barcode strip; falls back to top/bottom crop if the barcode isn't clearly separated
2. **Preprocessing** — up to 5 strategies (CLAHE, Otsu binary, adaptive threshold, scaled CLAHE, high contrast) run in parallel via a `ThreadPoolExecutor`
3. **Rotation fallback** — if the initial pass fails, tries 90°, 180°, 270° rotations with the same strategy set
4. **Blur/quality check** — Laplacian variance score rejects blank or near-blank images before wasting decode time
5. **Parse** — auto-detects format (MRZ vs Digital NID) and extracts structured fields

---

## Supported NID Formats

### Machine Readable Zone (MRZ)

Older NID cards. Barcode payload is ASCII with `\x1d` / `\x1e` delimiters.

| Field Code | Field |
|------------|-------|
| `NM` | Full name |
| `NW` | Smart card NID number |
| `OL` | Old NID number |
| `BR` | Date of birth (YYYYMMDD → DD Mon YYYY) |
| `DT` | Date of issue (YYYYMMDD → DD Mon YYYY) |
| `BG` | Blood group |

### Digital NID (XML)

Newer NID cards. Barcode payload is an XML fragment.

| Tag | Field |
|-----|-------|
| `<pin>` | NID / PIN number |
| `<name>` | Full name |
| `<DOB>` | Date of birth |
| `<F>` / `<FP>` | Fingerprint data |
| `<TYPE>` | Card type |
| `<V>` | Version |

---

## Quick Start

### Local (Python)

```bash
# Python 3.11+
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# macOS — required for pyzbar
brew install zbar

# Ubuntu/Debian — required for pyzbar
sudo apt-get install libzbar0

python main.py
# → http://localhost:8000
```

### Test immediately

```bash
# File upload
curl -X POST http://localhost:8000/scan \
  -F "file=@/path/to/nid-image.jpg"

# Base64
curl -X POST http://localhost:8000/scan/base64 \
  -H "Content-Type: application/json" \
  -d '{"image": "<base64-encoded-image>"}'

# Health check
curl http://localhost:8000/health
```

---

## Docker

### Local dev (hot reload)

```bash
docker compose -f docker-compose.local.yml up --build
```

Code changes in `main.py` and `app/` reload automatically. Logs at DEBUG level.

### Production

```bash
# Build and tag
docker build -t nid-barcode-scanner:v3.0.0 .

# Run
IMAGE_TAG=v3.0.0 docker compose -f docker-compose.prod.yml up -d

# Tail logs
docker compose -f docker-compose.prod.yml logs -f

# Stop
docker compose -f docker-compose.prod.yml down
```

**Resource limits (production):**
- CPU: 1.5 cores (0.5 reserved)
- Memory: 768 MB (256 MB reserved)
- Log rotation: 3 × 10 MB JSON files

The Docker image is multi-stage. The final runtime image is Python 3.11-slim with only the required system libraries (`libzbar0`, `libgl1`, etc.). Runs as a non-root user.

---

## API Reference

Base URL: `http://localhost:8000`

Interactive docs available at `/docs` (Swagger UI) and `/redoc` (ReDoc).

---

### `POST /scan`

Upload an image file. Accepts `multipart/form-data`.

**Request**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `file` | `UploadFile` | Yes | Image file |

**Allowed formats:** `jpg`, `jpeg`, `png`, `webp`, `bmp`  
**Max file size:** 10 MB  
**Min image dimensions:** 200 × 200 px

**Success response — 200**

```json
{
  "success": true,
  "message": "Barcode decoded successfully",
  "data": "<raw barcode string>",
  "parsed_data": {
    "name": "JOHN DOE",
    "nid_number": "1234567890",
    "old_nid": "123456789",
    "date_of_birth": "01 Jan 1990",
    "blood_group": "B+",
    "issue_date": "15 Mar 2020",
    "pin": null,
    "type": null,
    "version": null,
    "fingerprint": null
  },
  "barcode_type": "machine_readable",
  "format": "PDF417",
  "processing_time": 0.312,
  "method": "pyzbar+clahe"
}
```

**Failure response — 422**

```json
{
  "success": false,
  "message": "Could not decode — barcode unreadable",
  "error": "Could not decode barcode",
  "processing_time": 1.204,
  "suggestions": [
    "Image appears blurry — use a focused, well-lit photo",
    "Ensure the barcode is clearly visible and not damaged",
    "Try better lighting without glare or shadows",
    "Use a higher resolution image",
    "Make sure the entire barcode is within the frame",
    "Confirm the barcode is a valid PDF417 format"
  ]
}
```

**Error codes**

| Code | Reason |
|------|--------|
| `400` | Missing filename, corrupt image, or unreadable file |
| `413` | File exceeds 10 MB |
| `415` | Unsupported file type |
| `422` | Valid image, barcode could not be decoded |
| `429` | Rate limit exceeded |

---

### `POST /scan/base64`

Submit a base64-encoded image. Accepts `application/json`.

**Request body**

```json
{
  "image": "<base64 string>"
}
```

Both plain base64 and data URIs are accepted:

```
data:image/jpeg;base64,/9j/4AAQ...
/9j/4AAQ...
```

**Responses** — same schema as `POST /scan`.

---

### `GET /health`

Returns service status and available decoders.

**Response — 200**

```json
{
  "status": "healthy",
  "service": "NID Barcode Scanner",
  "version": "3.0.0",
  "available_decoders": ["pyzbar", "pdf417decoder"]
}
```

`available_decoders` reflects what's actually loaded at runtime. `pyzbar` requires `libzbar0`; if it's missing, only `pdf417decoder` will be listed.

---

### `GET /`

Returns service info and endpoint map. Not included in the OpenAPI schema.

---

## Configuration

All settings can be overridden with environment variables (case-insensitive). No restart required when using Docker env injection.

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `THREAD_WORKERS` | `3` | Parallel preprocessing threads |
| `TIMEOUT_SECONDS` | `15` | Max processing time per request |
| `MAX_FILE_SIZE_MB` | `10` | Upload size cap |

Example `.env` file:

```env
LOG_LEVEL=DEBUG
THREAD_WORKERS=4
TIMEOUT_SECONDS=20
MAX_FILE_SIZE_MB=15
```

**Note:** The service runs with a single uvicorn worker. The `ThreadPoolExecutor` handles all concurrency. Running multiple uvicorn workers would multiply memory usage without improving throughput for this workload.

---

## Rate Limiting

Per-IP limits apply to all scan endpoints:

| Window | Limit |
|--------|-------|
| Per minute | 10 requests |
| Per day | 30 requests |

Exceeded limits return **HTTP 429**. Headers include `Retry-After`.

This is enforced at the application layer via [slowapi](https://github.com/laurentS/slowapi). If you're deploying behind a reverse proxy (nginx, Caddy, Traefik), set `X-Forwarded-For` correctly so the real client IP is used, not the proxy IP.

---

## Decoder Priority

The service tries decoders in this order, stopping at the first success:

1. **pyzbar** — C++ backed (via `libzbar0`). Fastest. Handles most cards.
2. **pylibdmtx** — Alternative C library. Disabled by default (uncomment in `requirements.txt` to enable).
3. **pdf417decoder** — Pure Python fallback. Always available. Slower but no system dependency.

Check `GET /health` to see which decoders are active at runtime.

---

## Project Structure

```
nid-barcode-reader/
├── main.py                    # App factory: lifespan, middleware, router
├── requirements.txt
├── Dockerfile                 # Multi-stage build (builder + slim runtime)
├── docker-compose.local.yml   # Local dev — hot reload, DEBUG logs
├── docker-compose.prod.yml    # Production — resource limits, log rotation
└── app/
    ├── config.py              # pydantic-settings — all tuneable values
    ├── models.py              # Pydantic models: NIDData, ScanResponse, etc.
    ├── parsers.py             # MRZ and Digital NID format parsers
    ├── preprocessing.py       # Region detection + image strategy variants
    ├── decoders.py            # Decoder wrappers + try_decode() dispatcher
    ├── scanner.py             # Full pipeline orchestration
    ├── limiter.py             # slowapi Limiter instance (shared)
    └── routes.py              # FastAPI router — all endpoints
```

---

## Contributing

### Prerequisites

- Python 3.11+
- `libzbar0` (Linux) or `zbar` via Homebrew (macOS) for the pyzbar decoder
- Docker (optional, for container testing)

### Setup

```bash
git clone <repo-url>
cd nid-barcode-reader
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

### Where things live

| What you want to change | Where to look |
|------------------------|---------------|
| Add a new parsed field | `app/models.py` (NIDData) + `app/parsers.py` |
| Add a preprocessing strategy | `app/preprocessing.py` → `smart_preprocess()` (keep under 8 strategies) |
| Add a new decoder | `app/decoders.py` — follow the existing pattern, add to `_DECODERS` in priority order |
| Add a new endpoint | `app/routes.py` |
| Change a limit or default | `app/config.py` |

### Rules

- **Do not break `ScanResponse` or `NIDData` field names** — downstream consumers depend on them. Adding new optional fields is fine.
- **Never write to disk** — all image processing must stay in-memory. The `np.frombuffer → cv2.imdecode` pattern is the only acceptable way to load images.
- **One uvicorn worker** — don't change this. The `ThreadPoolExecutor` on `app.state.executor` is the concurrency mechanism.
- **Decoder priority order is intentional** — pyzbar → pylibdmtx → pdf417decoder. Don't reorder without profiling.
- Keep `smart_preprocess()` under 8 strategies to avoid thread pool saturation.

### Submitting changes

1. Fork the repo and create a branch from `main`
2. Make your changes
3. Verify the service starts and `/health` returns 200
4. Test your change with a real NID image if possible
5. Open a pull request with a clear description of what changed and why

---

## License

Check the repository root for license information.
