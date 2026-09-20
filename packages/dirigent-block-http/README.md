# dirigent-block-http

The HTTP block family: `http.request` calls an endpoint, `http.ready` waits for one to answer,
and `webhook.post` sends a JSON body that can carry an HMAC signature.

It registers the `http` connection kind, which is where a base URL, its credential, its TLS
settings and its timeouts are held, so a step names a connection rather than a URL and a
secret. The configuration and the client behind that kind are `dirigent-common`'s, and any
pack may use them; the registration is this family's.
