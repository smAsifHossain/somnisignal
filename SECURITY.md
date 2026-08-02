# Security and privacy design

- The laptop binds FastAPI to localhost and must be reached only through an
  authenticated HTTPS tunnel and the Cloudflare Worker.
- The Worker is the CORS boundary. Laptop CORS middleware is intentionally absent.
- The Worker never exposes the reserved clinical endpoint. Its public upload route
  requires confirmation that the user is authorized to analyze the adult ECG data.
- API bearer tokens are compared through fixed-length SHA-256 digests using a
  constant-time comparison.
- No access log is emitted. Application code does not log filenames, samples,
  headers, request bodies, IP addresses, or results.
- Uploads are limited during request streaming and again while the compressed file
  is copied. Processing uses a 128 MB temporary filesystem and deletes raw files on
  success, failure, cancellation, or expiry.
- Only one job is accepted at a time; job IDs are random 128-bit values and in-memory
  results expire after 15 minutes.
- The container has a read-only root, non-root user, two CPU limit, 768 MB memory
  limit, PID limit, and no-new-privileges.

Report vulnerabilities privately to the repository owner. Share only the minimum
technical detail required, remove identifying or confidential information, and
never include API tokens or tunnel URLs.
