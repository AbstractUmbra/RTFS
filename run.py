import os

import uvicorn

if __name__ == "__main__":
    host = "127.0.0.1" if os.getenv("RTFS") else "0.0.0.0"
    conf = uvicorn.Config("rtfs:APP", host=host, port=8030, workers=5)
    server = uvicorn.Server(conf)

    server.run()
