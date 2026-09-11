# S3 examples

Object storage without an S3 block anywhere: `s3://` is a registered URI scheme, so the
ordinary storage blocks address it the way they address anything else,
and every document here declares `requires: {storage: [s3]}` so an instance without a
backend refuses it before storing it.

All five name one connection, `artifacts`, and it is the code the
[compose stack](../../docs/operations.md) already bootstraps for its own artifact bucket. So
on the stack there is nothing to set up: apply and run, naming the stack's bucket.

```bash
dg run s3-round-trip -p day=2026-01-01 -p bucket=dirigent --watch
```

Under `dg dev` there is no S3 server and no connection, and
[s3-round-trip.yaml](s3-round-trip.yaml) documents both: the rustfs container to start, the
`artifacts` connection to create, and the `DIRIGENT_STORAGE_CONNECTIONS` line that makes it
serve the scheme.

```bash
dg apply examples/s3/s3-round-trip.yaml
dg run s3-round-trip -p day=2026-01-01 --watch
```

## Pipelines

| File | What it teaches |
| --- | --- |
| [s3-round-trip.yaml](s3-round-trip.yaml) | The whole seam: an artifact out to a bucket and back, moved by the ordinary storage blocks. |
| [s3-copy-and-verify.yaml](s3-copy-and-verify.yaml) | Promote-then-consume: a copy between prefixes, and `storage.exists` standing between the copy and the reader. |
| [s3-csv-report.yaml](s3-csv-report.yaml) | A report delivered to a bucket: the csv-report chain with the converter's `target` one word away from scratch. |
| [report-to-s3.yaml](report-to-s3.yaml) | A rendered markdown page delivered to a bucket: `report.render` hands its text on and `storage.write` puts it in the object, content type and all. |
| [s3-parquet-report.yaml](s3-parquet-report.yaml) | A typed parquet dataset written straight to a bucket, for an analysis to open (needs `dirigent-parquet`). |
