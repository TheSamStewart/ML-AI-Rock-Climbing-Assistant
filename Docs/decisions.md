# Document which outlines different design decisions made and why (for me)

ctrl + k then v to preview in vs code

## Why Async Design

Asynchronus Design pattern was chosen as the window between the applications request and the backend's reply can exceed 20s. Keeping a synchronous HTTP connection open for this duration risks connection timeouts and client-side disconnections. Instead the application will issue a POST to initiate the task. The API will then issue a 202 accepted and return a TASKID to the application. The Application will then perform polling via GET requests to a status endpoint until the job is complete.

## Brief explanation of each part of the stack and why it was chosen.

### <ins>React Native:</ins>

Explanation:

React Native allows for development in one language, that through the JavaScript Interface (jsi) allows the JS to call pre-existing native code. The JavaScript Interface utilises C++ wrappers to allow JavaScript to directly call upon native platform APIs (like getBatteryLevel). A wrapper is a C++ function which executes pre-compiled native methods. When our JS engine executes the JS call, this triggers the C++ wrapped which returns our result back in JS.

Why Chosen:

React Native is one of the most popular and modern frameworks for mobile frontends in 2026. I have experience using JavaScript and React so this was a comfortable choice.

### <ins>FastAPI RESTAPI</ins>:

Explanation:

#### FastAPI

FastAPI is built on Starlette a fast Asynchronous Server Gateway Interface toolkit (ASGI). This allows fastAPI to send, receive and perform small tasks all on one thread. WSGI would perform these together on one thread (one thread = one request).

WSGI (Sequential/Blocking): Request -> Wait for work to be done -> Return payload. (1 thread = 1 active request).

ASGI (Concurrent/Non-Blocking): Request -> While work is being done, take other requests/other work -> Return payload. (1 thread = many concurrent requests).

#### RESTAPI

RESTAPI (Representational State Transfer) is an architecture for API design where the API is stateless. Statelessness means the API does not store any session state, every HTTP request must be self contained - in our case containing the related TASKID.

The frontend makes the request -> API drops the task in redis queue -> API returns the TASKID to the frontend -> moves onto next task.

This combined with the frontend polling GET while the task is being performed keeps our concerns separated and allows the API to process thousands of requests upholding the Async architecture.

Why Chosen:

#### FastAPI

FastAPI has been chosen for this project for two main reasons:

FastAPI is built on an asynchronous architecture (ASGI), which facilitates and supports the high-concurrency design of this application (i.e., managing a high volume of polling requests while offloading tasks to a background worker queue).

FastAPI is also written in Python, a language I am comfortable with through DSA questions.

#### RESTAPI

The REST architecture supports our application's scalability by keeping all HTTP requests stateless. Because the API must immediately terminate the session with the client to avoid disconnections, we cannot rely on persistent server-side sessions. Instead, it is imperative that we track long-running operations statelessly by issuing a unique TASKID to the client, which they must provide in subsequent polling requests to retrieve the task's progress.

### <ins>Redis</ins>

Explanation:

Redis is an open-source in memory (uses RAM) data-structure, is a key-value store that supports strings, lists, sets. Celery uses Redis's native data-structures (lists) to implement a task-queue

Why Chosen:

By acting as a message-broker (task-queue) Redis facilitates background task execution allowing our Celery workers to process thousands of tasks completely seperate from our API. Redis stores the result from our Celery worker and, due to it's in memory (RAM) key-value architecture allows our API to return the result to the front-end in miliseconds once work is complete.

### <ins>Celery</ins>

Explanation:

Celery is an open-source tool written in Python that utilises Redis to manage a Task Queue. When a task is added to the Queue using (`my_task.delay(arg)`) Celery serializes the Python args (in our case this would be a Base64 image string) into JSON format so they can travel across the network. Celery also generates a unique TASKID which the frontend uses to poll and retrieve the completed work.

Why Chosen:

Celery abstracts the complexity of the asynchronous processing system by handling task serialization, worker concurrency, and Redis queue management automatically in the background.

### <ins>Yolo26-seg</ins>

Explanation:

Yolo26 is the most recent model architecture released by Ultralytics. YOLO is used because its eco-system (Ultralytics) make it intuitive to train and run predictions using the model.

Why Chosen:

For the eco-system that make custom-trained ML models achievable to people who are not experts in the Mathematics behind them. Segmentation is used due to the intricate shape or rock climbing holds, simple bounding boxes could lead to confusing annotations where holds overlap.

## Image Storage

This defines the image journey from user to worker.

1. The frontend will make a POST request in which it will recieve information on where to store the image (URL or something).
2. Frontend will store image at this place.
3. Worker script and frontend are free to access this image as needed.
4. 
## Why expo 54.0.0

- Expo go on app store does not support the latest versions of Expo unless using paid Apple Developer program.
