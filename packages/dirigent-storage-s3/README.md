# dirigent-storage-s3

The `s3://` storage backend for dirigent, for AWS S3 and any S3-compatible endpoint.

Registers the `s3` URI scheme and an `s3` connection kind. URIs are `s3://bucket/key`; the
bucket is always carried by the URI, never inferred.

- **Reads stream.** `open_read` yields bounded chunks off the object body, so copying a
  multi-gigabyte artifact is never resident.
- **Writes are all-or-nothing.** A small write lands as one `put_object`. Once the buffer
  crosses 5 MiB it becomes a multipart upload, completed only on a clean exit and aborted on
  any exception, so a reader never sees a half-written object.
- **Listing takes a prefix or a glob.** The fixed part of the pattern becomes the S3
  `Prefix`; the returned keys are filtered with `fnmatch`, so `*` matches across `/`.
- **Any S3 API.** Set `endpoint_url` and `path_style` to address a self-hosted or
  third-party S3-compatible endpoint; leave both alone for AWS S3 itself.

The `s3` connection check does a `head_bucket` when the connection names a default bucket and
a `list_buckets` otherwise, and reports rather than raises.

Integration tests run against a real S3-compatible server under the `s3` marker, which the
default test lane excludes: `uv run pytest packages/dirigent-storage-s3 -m s3`.
