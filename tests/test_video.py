from fastapi.testclient import TestClient
from fastapi.routing import APIRoute
from app.routers.video import updateArtifact
from app.main import app
from app.constants import deviceId
from app import db
import os
import pytest
import requests
import json
from google.cloud.firestore_v1.base_query import FieldFilter

def endpoints():
    endpoints = []
    for route in app.routes:
        if isinstance(route, APIRoute):
            endpoints.append(route.path)
    return endpoints
@pytest.fixture
def client():
    client = TestClient(app, "http://0.0.0.0:3000")
    yield client
@pytest.fixture
def user():
    url = "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=" + os.environ.get("FIREBASE_API_KEY")
    
    payload = json.dumps({
    "email": "test_video@gmail.com",
    "password": "testing",
    "returnSecureToken": True
    })
    headers = {
    'Content-Type': 'application/json'
    }
    response = requests.request("POST", url, headers=headers, data=payload)
    data = response.json()
    user = {"id": data['localId'], "token": data["idToken"]}
    yield user
    db.collection("user").document(user['id']).delete()
class TestVideoAPI:
    @pytest.mark.skipif("/video" not in endpoints(),reason="Route not defined")
    def test_video_API(self, user, client):
        # Test when no token is pass to route
        payload = {}
        files=[
        ('file',('demo.mp4',open('demo.mp4','rb'),'video/mp4'))
        ]
        headers = {
        }
        response = client.request("POST", 'video', headers=headers, data=payload, files=files)
        assert response.status_code == 403
        # Test when a dummy (not valid) token passed
        payload = {}
        files=[
        ('file',('demo.mp4',open('demo.mp4','rb'),'video/mp4'))
        ]
        headers = {
        'Authorization': "Bearer saikoljncaskljnfckjnasckjna"
        }
        response = client.request("POST", 'video', headers=headers, data=payload, files=files)
        assert response.status_code == 401
        # Test when sent file is not a video
        db.collection("user").document(user['id']).set({"deviceId": deviceId})
        payload = {}
        files=[
        ('file',('demo.jpg',open('demo.jpg','rb'),'application/octet-stream'))
        ]
        headers = {
        'Authorization': "Bearer " + user['token']
        }
        response = client.request("POST", 'video', headers=headers, data=payload, files=files)
        assert response.status_code == 400
        # Test when all requirements have been fulfilled
        payload = {}
        files=[
        ('file',('demo.mp4',open('demo.mp4','rb'),'video/mp4'))
        ]
        headers = {
        'Authorization': "Bearer " + user['token']
        }
        response = client.request("POST", 'video', headers=headers, data=payload, files=files)
        assert response.status_code == 200
        artifactName = response.text
        docs = db.collection("artifacts").where(filter = FieldFilter("name", '==', artifactName)).stream()
        index = 0
        for doc in docs:
            # For each document in docs. Verify name and status of the artifact
            index += 1
            data = doc.get().to_dict()
            assert data['name'] == artifactName
            assert data['status'] == 'pending'
            assert index == 1
            doc.delete()
    def test_update_artifact(self):
        # Check and preprocess test data before testing
        test_artifact = db.collection("artifacts").document('test')
        if not test_artifact.get().exists:
            db.collection("artifacts").document('test').set({"name": "test", "path": "", "status": "testing", "thumbnailURL":""})
            test_artifact = db.collection("artifacts").document('test')
        else:
            test_artifact.update({"status": "testing", 'path': '', "thumbnailURL":""})
        # Testing update on each field
        updateArtifact(test_artifact.id,{"status": "test_done"})
        assert db.collection("artifacts").document('test').get().to_dict()['status'] == 'test_done'
        #Delete data for next time test
        test_artifact.delete()
        
            