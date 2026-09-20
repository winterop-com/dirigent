# dirigent-block-storage

The storage block family: `storage.copy` moves an object from one URI to another,
`storage.write` puts a value or text at one, `storage.read` brings one back as a value, and
the `storage.exists` sensor waits for one to appear.

Every block here speaks whatever URI schemes the instance has registered, so a backend pack
such as `dirigent-storage-s3` widens what these four can address without changing them. The
family depends on nothing but the contract packages.
