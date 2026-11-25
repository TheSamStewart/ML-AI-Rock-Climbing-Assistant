# ML-AI-Rock-Climbing-Assistant
AI-powered beta generator for rock climbers. Take one photo of a climbing wall, tap the holds on your route, and get step-by-step coaching on how to climb it, all in a mobile app.

---

## How it works

1. **Snap a photo** of the wall in the app.
2. **Holds are found automatically.** A custom-trained YOLO26-seg model detects every hold in the photo within seconds.
3. **Pick your route.** Tap the holds you want to climb. The app shows each hold's real outline and the distance between them.
4. **Measure the wall.** Gym walls have a regular grid of bolt holes, which the backend uses as a ruler to work out real distances between holds and how steep each section is (slab, vertical, overhang, roof).
5. **Get coached.** The route and its measurements are sent to a background worker, which asks an LLM (Claude) for coaching. The app shows the result as a numbered list of moves, each with the reason behind it.

```
 Mobile app ──photo──▶ API ──▶ YOLO hold detection + wall measurement
     │                  │
     └──chosen holds───▶ API ──▶ job queue (Redis) ──▶ worker ──▶ LLM coaching
     ◀──────── polls for the finished steps ─────────────────────────┘
```

The slow AI step runs in the background, so the app stays responsive and simply checks back until the coaching is ready. Repeated or retried requests are handled safely, so nothing gets processed twice.

---

### What I'm working on right now:
* Improving the accuracy of the wall measurements on real gym photos.
* Giving the LLM richer detail about the route so its coaching is more specific.

---

### Learning Goals for this project:
* **CI/CD Automation:** Continuous integration and testing pipelines using GitHub Actions.
* **Cross-Platform UI & State Management:** Build the mobile client using React Native, focusing on asynchronous UI updates.
* **Asynchronous REST API:** Design a stateless backend with FastAPI that validates and routes requests.
* **Distributed Task Queues:** Keep heavy AI work off the web server with a Producer-Consumer setup using Celery and Redis.
* **Relational Data Persistence:** Store system state and results in MariaDB *(planned)*.
* **MLOps:** Train and deploy custom computer vision models behind a production-grade inference pipeline.

---

## Technical Stack

| Component | Technology |
| :--- | :--- |
| **Mobile** | React Native (Expo) |
| **Backend** | Python, FastAPI |
| **Task Queue (workers)** | Redis, Celery |
| **CV Model** | YOLO26-seg trained on 2000+ images of bouldering-gym walls |
| **AI Coaching** | Claude API (structured JSON output) |
| **Infrastructure** | Docker, Docker Compose |
| **Testing / CI** | Pytest, GitHub Actions, load testing |
| **Database** | MariaDB *(planned)* |

---

## More detail
* [docs/architecture.md](docs/architecture.md): how the pieces fit together, the full API contract
* [docs/decisions.md](docs/decisions.md): why each technology was chosen
* [docs/localhost.md](docs/localhost.md): running the full stack locally
