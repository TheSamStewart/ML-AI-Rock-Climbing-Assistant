# ML-AI-Rock-Climbing-Assistant
AI-powered beta generator for rock climbers. Uses YOLO26 and LLM reasoning to map routes and suggest movement sequences from a single photo.

---

### What I'm working on right now:  
* Training the Computer Vision model to reach my success criteria:
  * Precision (M): >= 0.70
  * Recall (M): >= 0.70
  * mAP50-95 (M): >= 0.40

---
  
### Why am I doing this:
* To gain experience integrating Computer Vision (YOLO) and LLMs.  
* To gain experience with Mobile Development in Swift.
* To consolidate experience using APIs to send and recieve data.
  
---

# UNNAMED
**A local-cloud hybrid system for rock climbing route analysis and beta generation.**

This system allows users to photograph a climbing wall, select specific holds via a tap-to-select interface, and receive a generated movement sequence (beta) based on the geometry and orientation of the holds.

## Architecture Overview

### 1. Mobile Client (Swift)
* **Capture:** High-resolution photo capture, automatically resized to 640x640 to match the YOLO26-seg input requirements.
* **Interactive Layer:** A human-in-the-loop UI where users tap the holds they intend to use. 
* **Normalization:** Screen taps are converted to normalized coordinates (0.0 to 1.0) before being sent to the server to ensure consistency across different device aspect ratios.

### 2. API Layer (FastAPI)
* **Endpoint:** `POST /analyze-route`
* **Payload:** Multipart form data containing the .jpg image and a JSON array of user-tapped coordinates.
* **Orchestration:** Manages the hand-off between the local CV model and the remote LLM API.

### 3. Detection Engine (YOLO26-seg)

* **Segmentation:** Reaplaces bounding boxes with polygons for pixel-perfect accuracy.
* **Filtering:** Uses a Point-in-Polygon algorithm to match user taps to specific detected instances, filtering out "noise" (holds from adjacent routes).

### 4. Reasoning Brain (LLM)
* **Prompting:** Sends the processed image and the filtered hold coordinates to the LLM.
* **Context:** The model analyzes the hold types (crimps, jugs, slopers) and their relative distances to generate an ergonomically sound climbing sequence.

### 5. Output and Visualization
* **Data Contract:** The server returns a JSON payload containing a step-by-step text sequence and pixel-coordinate markers for the app to render.
* **Rendering:** Swift renders a visual overlay (numbered path) directly onto the user's original photo.

---

## Technical Stack

| Component | Technology |
| :--- | :--- |
| **Mobile** | Swift (UIKit/SwiftUI) |
| **Backend** | Python, FastAPI |
| **CV Model** | YOLO26-seg |
| **LLM API** | UNSPECIFIED |
| **Tunneling** | ngrok |

---
