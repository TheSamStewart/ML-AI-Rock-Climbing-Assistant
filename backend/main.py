from fastapi import FastAPI
from worker import add

app = FastAPI() 

@app.get("/add")
def add_numbers(x : int, y : int):
    
    #Drops the task into the redis queue for processing by the worker

    task = add.delay(x,y)

    #Tells the user the task is being processed, if not ok will return 400 

    return {
        "message" : "Task submitted successfully",
        "task_id" : task.id
    }



