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
        env_file:
            - .env
```

You need to provide the .env file, ideally from the `.env.template` file provided.

### No Docker
You can run this by installing the necessary dependencies defined in the `pyproject.toml` and running `run.py`. You'll need to set an `API_TOKEN` environment variable in this case with a unique secure value.
