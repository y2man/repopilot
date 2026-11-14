import io, uuid, zipfile
from fastapi.testclient import TestClient
from app.main import app

def zipped():
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w') as z:
        z.writestr('demo/src/auth.py','def authenticate(user, password):\n    return check_password(password)\n')
        z.writestr('demo/.env','API_KEY=should-not-index')
    return b.getvalue()

def test_register_upload_list_files_and_owner_isolation():
    with TestClient(app) as client:
        email=f"test-{uuid.uuid4().hex}@example.com"
        response=client.post('/api/v1/auth/register',json={'email':email,'password':'long-secure-test-password'})
        assert response.status_code==200, response.text
        token=response.json()['access_token']
        headers={'Authorization':f'Bearer {token}'}
        assert client.get('/api/v1/auth/me',headers=headers).json()['email']==email
        uploaded=client.post('/api/v1/repositories/upload',headers=headers,files={'file':('demo.zip',zipped(),'application/zip')})
        assert uploaded.status_code==201, uploaded.text
        repo=uploaded.json()
        assert repo['file_count']==1 and repo['chunk_count']==1
        files=client.get(f"/api/v1/repositories/{repo['id']}/files",headers=headers)
        assert files.status_code==200 and files.json()[0]['path']=='demo/src/auth.py'
        assert client.get(f"/api/v1/repositories/{repo['id']}/files/content?path=demo%2Fsrc%2Fauth.py",headers=headers).status_code==200
        other=client.post('/api/v1/auth/register',json={'email':f"other-{uuid.uuid4().hex}@example.com",'password':'long-secure-test-password'})
        other_headers={'Authorization':f"Bearer {other.json()['access_token']}"}
        assert client.get(f"/api/v1/repositories/{repo['id']}",headers=other_headers).status_code==404
        assert client.get('/api/v1/repositories').status_code==401

def test_chat_does_not_fake_ai_when_provider_key_missing(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr('app.services.llm.get_settings', lambda: SimpleNamespace(groq_api_key=None))
    with TestClient(app) as client:
        email=f"chat-{uuid.uuid4().hex}@example.com"
        auth=client.post('/api/v1/auth/register',json={'email':email,'password':'long-secure-test-password'}).json()
        headers={'Authorization':f"Bearer {auth['access_token']}"}
        repo=client.post('/api/v1/repositories/upload',headers=headers,files={'file':('demo.zip',zipped(),'application/zip')}).json()
        response=client.post('/api/v1/chat',headers=headers,json={'repository_id':repo['id'],'question':'Explain authentication in this code'})
        assert response.status_code==503
        assert 'GROQ_API_KEY' in response.json()['detail']


def test_audit_events_are_owner_scoped_and_record_authentication():
    with TestClient(app) as client:
        email = f"audit-{uuid.uuid4().hex}@example.com"
        registered = client.post('/api/v1/auth/register', json={
            'email': email, 'password': 'long-secure-audit-password-123'})
        headers = {'Authorization': f"Bearer {registered.json()['access_token']}"}
        client.post('/api/v1/auth/login', json={
            'email': email, 'password': 'long-secure-audit-password-123'})
        events = client.get('/api/v1/audit?limit=20', headers=headers)
        assert events.status_code == 200
        actions = [event['action'] for event in events.json()]
        assert 'auth.register' in actions and 'auth.login' in actions
        other = client.post('/api/v1/auth/register', json={
            'email': f"other-audit-{uuid.uuid4().hex}@example.com",
            'password': 'long-secure-audit-password-123'})
        other_headers = {'Authorization': f"Bearer {other.json()['access_token']}"}
        other_events = client.get('/api/v1/audit?limit=20', headers=other_headers).json()
        assert all(event['action'] == 'auth.register' for event in other_events)
