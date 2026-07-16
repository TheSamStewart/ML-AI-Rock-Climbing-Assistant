# Notes on running the application with Docker

1. in WSL run cd /mnt/c/Personal_Project/ML-AI-Rock-Climbing-Assistant

2. Run docker compose up --build to start the container. This starts the redis database server, spins up a container running the FastAPI server, and spins a container to run the Celery worker

3. Test as nesscary, for example searching http://localhost:8000/add?x=2&y=3 will 202 accepted.
