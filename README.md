# ML-AI-Rock-Climbing-Assistant
AI-powered beta generator for rock climbers. Uses YOLO26 and LLM reasoning to map routes and suggest movement sequences from a single photo.

---

### What I'm working on right now:  
* Building snapchat style front-end in React Native
* Planning/slowly implementing backend infrastructure

---
  
### Learning Goals for this project:
* **CI/CD Automation:** Establish continuous integration and testing pipelines using GitHub Actions.
* **Cross-Platform UI & State Management:** Build the mobile client using React Native, focusing on asynchronous UI updates.
* **Asynchronous REST API:** Design a stateless backend utilizing FastAPI to securely orchestrate network payloads and data validation.
* **Distributed Task Queues:** Decouple heavy ML computation from the web server by implementing a Producer-Consumer architecture with Celery and Redis.
* **Relational Data Persistence:** Manage system state and inference results using MariaDB.
* **MLOps & Inference Deployment:** Train and deploy custom computer vision models behind a production-grade inference pipeline.

---

### Workflow Diagram:
![ML Rock Climbing App Workflow Diagram](https://raw.githubusercontent.com/TheSamStewart/ML-AI-Rock-Climbing-Assistant/refs/heads/main/ML-Rock-Climbing-App-Workflow-Diagram_3.svg)

---

## Technical Stack

| Component | Technology |
| :--- | :--- |
| **Mobile** | React Native |
| **Backend** | Python, FastAPI |
| **Task Queue(workers)** | Redis, Celery |
| **Database** | MariaDB |
| **CV Model** | YOLO26-seg trained on 2000+ images of bouldering-gym walls |
| **LLM API** | UNSPECIFIED 
