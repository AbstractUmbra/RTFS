# RTFS

## Running this

There's a provided compose & Dockerfile as well as published image on GHCR.

You need to provide the secrets file which contains the owner/admin api key.
You can make one really quickly using the following command:-
```sh
openssl rand -base64 64 > api_key
```
Which will generate a secure and random key for you.

### No Docker
You can run this by installing the necessary dependencies defined in the `pyproject.toml` and running `run.py`. You'll need to set an `API_KEY_FILE` environment variable in this case which points to a file with a secure key within.
Optionally, if you want to run this on localhost only, set a `RTFS` environment variable with any value.
