# Plan for learning TDD

## test_main.py

- To create fake versions of celery and redis, we use patch() to override the calls made to the real redis/celery in our test API client.
- To create a fake return for our celery task, we use mock_task.return_value.id to set the return value of the task
