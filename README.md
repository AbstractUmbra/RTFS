# RTFS

## Running this

There's a provided Dockerfile as well as published image on GHCR.
An example docker compose file that can run this is the following:-

```yaml
services:
    rtfs:
        image: ghcr.io/abstractumbra/rtfs
        container_name: rtfs
        ports:
            - 8130:8130
        secrets:
            API_KEY_FILE: /run/secrets/api_key

secrets:
    api_key:
        file: ./api_key
```

You need to provide the secrets file which contains the owner/admin api key.
You can make one really quickly using the following command:-
```sh
openssl rand -base64 64 > api_key
```
Which will generate a secure and random key for you.

### No Docker
You can run this by installing the necessary dependencies defined in the `pyproject.toml` and running `run.py`. You'll need to set an `API_KEY_FILE` environment variable in this case which points to a file with a secure key within.
