import io
import uuid
import fakeredis
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch 
from mock import AsyncMock
from main import app

#create a test client instance wrapping the app (FastAPI)
client = TestClient(app)

#Create fake celery task

@pytest.fixture(autouse=True)
def mock_celery_task():
    
    with patch("main.analysis_task.delay") as mock_task:

        mock_task.return_value.id = "test-task-id-1234"

        yield mock_task

#Fake redis

@pytest.fixture(autouse=True)
def mock_redis_client():

    fake_redis = fakeredis.aioredis.FakeRedis()

    with patch("main.redis_client", fake_redis):

        yield fake_redis

def test_post_already_processing():

    with patch("main.redis_client.set", new_callable=AsyncMock) as mock_redis_set, \
    patch("main.redis_client.get", new_callable=AsyncMock) as mock_idem_key_check:

        mock_redis_set.return_value = False
        mock_idem_key_check.return_value = "processing"

        fake_image_data = io.BytesIO(b"fake binary image contents")
        
        files = {"photo": ("test_image.jpg", fake_image_data, "image/jpeg")}
        
        headers = {
            "Idempotency-Key": str(uuid.uuid4())
        }
        
        #Make POST to the api test client 
        
        response = client.post("/analysis", files=files, headers=headers)

        assert response.status_code == 409

        data = response.json()

        assert data["detail"] == "Request with this Idempotency-Key is already being processed"


def test_post_image():

    #Create fake data

    fake_image_data = io.BytesIO(b"fake binary image contents")

    files = {"photo": ("test_image.jpg", fake_image_data, "image/jpeg")}

    headers = {
        "Idempotency-Key": str(uuid.uuid4())
    }

    #Make POST to the api test client 

    response = client.post("/analysis", files=files, headers=headers)

    #Check status 202 is returned for good data

    assert response.status_code == 202

    data = response.json()

    #Ensure we recieve a task_id

    assert "task_id" in data
    assert isinstance(data["task_id"], str)
    assert len(data["task_id"]) > 0

def test_get_analysis_failure():

    #First we replace the AsyncResult call in getAnalysis with our mock one

    with patch("main.AsyncResult") as mock_async_result:

        #Configure the mock instance that AsyncResult returns

        mock_instance = mock_async_result.return_value
        mock_instance.state = "FAILURE"
        mock_instance.result = Exception("Something went wrong")

        #Hit the get endpoint with fake task id

        response = client.get("/analysis/test-task-id-1234")

        #Check for the correct reponse

        assert response.status_code == 200
        
        data = response.json()

        assert data["task_id"] == "test-task-id-1234"
        assert data["status"] == "FAILURE"
        assert data["error"] == "Something went wrong"

def test_get_analysis_pending():

    with patch("main.AsyncResult") as mock_async_result:

        mock_instance = mock_async_result.return_value
        mock_instance.state = "PENDING"

        response = client.get("/analysis/test-task-id-1234")

        assert response.status_code == 200

        data = response.json()

        assert data["task_id"] == "test-task-id-1234"
        assert data["status"] == "PENDING"


        

