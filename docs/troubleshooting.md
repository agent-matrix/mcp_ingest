# Troubleshooting

### Docker not found
Install Docker and ensure it is on PATH. Container validation requires a local Docker daemon.

### SSE preflight fails
Check that your server listens on `/sse` and reachable on the expected port. Try `curl -N http://127.0.0.1:6288/sse`.

### Git clone errors
Public repos should work without tokens. For private repos, provide credentials or use ZIP archives.

### MatrixHub 404 on /catalog/install
Verify MatrixHub is running and your `--matrixhub` URL is correct.