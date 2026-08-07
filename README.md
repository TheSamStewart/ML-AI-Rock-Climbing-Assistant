# ML-AI-Rock-Climbing-Assistant
AI-powered beta generator for rock climbers. Uses YOLO26 and LLM reasoning to map routes and suggest movement sequences from a single photo, provided to the user in a mobile application.

---

### What I'm working on right now:  
* Building Human-In-The-Loop system in frontend which allows user to tap on the climbing holds that are part of route they want to analyse.
* Implementing ML predictions in backend to be sent to LLM to provide human-like analysis.

---
  
### Learning Goals for this project:
* **CI/CD Automation:** Establish continuous integration and testing pipelines using GitHub Actions.
* **Cross-Platform UI & State Management:** Build the mobile client using React Native, focusing on asynchronous UI updates.
* **Asynchronous REST API:** Design a stateless backend utilizing FastAPI to securely orchestrate network payloads and data validation.
* **Distributed Task Queues:** Decouple heavy ML computation from the web server by implementing a Producer-Consumer architecture with Celery and Redis.
* **Relational Data Persistence:** Manage system state and inference results using MariaDB.
* **MLOps** Train and deploy custom computer vision models behind a production-grade inference pipeline.

---

## Technical Stack

| Component | Technology |
| :--- | :--- |
| **Mobile** | React Native |
| **Backend** | Python, FastAPI |
| **Task Queue(workers)** | Redis, Celery |
| **Database** | MariaDB |
| **CV Model** | YOLO26-seg trained on 2000+ images of bouldering-gym walls |
