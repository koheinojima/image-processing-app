from fastapi import FastAPI, BackgroundTasks, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import RedirectResponse
from pydantic import BaseModel
import asyncio
import os
import json
from processor import ImageProcessor
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials

app = FastAPI(title="Image Processing API")

# Allow CORS for frontend
origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    os.environ.get("FRONTEND_URL", "").strip(),
]
# Remove empty strings
origins = [o for o in origins if o]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Session Middleware for auth (SECRET_KEY should be in env for prod)
app.add_middleware(SessionMiddleware, secret_key=os.environ.get("SECRET_KEY", "dev_secret_key_12345"))

SCOPES = [
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/spreadsheets',
    'openid', 'https://www.googleapis.com/auth/userinfo.email', 'https://www.googleapis.com/auth/userinfo.profile'
]

class Config(BaseModel):
    project_name: str
    input_photo_folder_id: str
    input_logo_folder_id: str
    output_root_folder_id: str
    spreadsheet_id: str
    photo_width: int
    photo_height: int
    force_contain_mode: bool

# Global instance to hold state
processor_instance = None

@app.get("/")
def read_root():
    return {"status": "ok", "message": "Image Processing API is running"}

@app.get("/api/auth/login")
def login(request: Request):
    client_config = None
    
    # Priority 1: env var (for production)
    env_creds = os.environ.get("GOOGLE_CLIENT_SECRET_JSON")
    if env_creds:
        try:
            client_config = json.loads(env_creds)
        except json.JSONDecodeError:
            return {"error": "Invalid GOOGLE_CLIENT_SECRET_JSON format"}
            
    # Priority 2: local file (for dev)
    elif os.path.exists('credentials.json'):
         client_config = None # Flow.from_client_secrets_file handles path, but here we want dict or path logic adjustment
         # For simplicity, we stick to flow.from_client_secrets_file if path exists,
         # OR flow.from_client_config if we have the dict.
         pass
    
    if env_creds and client_config:
        flow = Flow.from_client_config(
            client_config,
            scopes=SCOPES,
            redirect_uri=os.environ.get("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/auth/callback")
        )
    elif os.path.exists('credentials.json'):
         flow = Flow.from_client_secrets_file(
            'credentials.json',
            scopes=SCOPES,
            redirect_uri=os.environ.get("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/auth/callback")
        )
    else:
        return {"error": "credentials.json not found and GOOGLE_CLIENT_SECRET_JSON not set"}
        
    authorization_url, state = flow.authorization_url(access_type='offline', include_granted_scopes='true')
    request.session['state'] = state
    return {"url": authorization_url}

@app.get("/api/auth/callback")
def auth_callback(request: Request, code: str, state: str):
    env_creds = os.environ.get("GOOGLE_CLIENT_SECRET_JSON")
    flow = None
    
    if env_creds:
        try:
            client_config = json.loads(env_creds)
            flow = Flow.from_client_config(
                client_config,
                scopes=SCOPES,
                state=state,
                redirect_uri=os.environ.get("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/auth/callback")
            )
        except:
             return {"error": "Invalid GOOGLE_CLIENT_SECRET_JSON"}
    elif os.path.exists('credentials.json'):
        flow = Flow.from_client_secrets_file(
            'credentials.json',
            scopes=SCOPES,
            state=state,
            redirect_uri=os.environ.get("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/auth/callback")
        )
    else:
        return {"error": "Server missing credentials configuration"}
    flow.fetch_token(code=code)
    creds = flow.credentials
    
    # Store credentials in session (serialized)
    request.session['credentials'] = {
        'token': creds.token,
        'refresh_token': creds.refresh_token,
        'token_uri': creds.token_uri,
        'client_id': creds.client_id,
        'client_secret': creds.client_secret,
        'scopes': creds.scopes
    }
    
    # Redirect back to frontend
    frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:3000")
    return RedirectResponse(url=f"{frontend_url}?authenticated=true")

@app.get("/api/auth/check")
def check_auth(request: Request):
    creds_data = request.session.get('credentials')
    if creds_data:
        return {"authenticated": True}
    return {"authenticated": False}

@app.post("/api/start")
async def start_process(config: Config, background_tasks: BackgroundTasks, request: Request):
    global processor_instance
    
    creds_data = request.session.get('credentials')
    if not creds_data:
        # Fallback to local file if simple local run (or error)
        # But for web flow, we strictly need this usually.
        # We will allow processor to fallback to local file if not passed, 
        # but warn here.
        pass

    if processor_instance and processor_instance.status == "running":
        return {"status": "error", "message": "Already running"}

    # Initialize new processor with config AND credentials
    processor_instance = ImageProcessor(config.dict(), creds_data)
    
    # Run in background
    background_tasks.add_task(processor_instance.run_process)
    
    return {"status": "started"}

@app.post("/api/stop")
def stop_process():
    global processor_instance
    if processor_instance and processor_instance.status == "running":
        processor_instance.stop_requested = True
        return {"status": "stopping"}
    return {"status": "failed", "message": "No running process"}

@app.get("/api/status")
def get_status():
    global processor_instance
    if processor_instance:
        return {
            "status": processor_instance.status,
            "logs": processor_instance.logs,
            "result_links": processor_instance.result_links,
            "progress": {
                "processed": processor_instance.processed_count,
                "total": processor_instance.total_files
            }
        }
    return {"status": "idle", "logs": [], "result_links": None, "progress": None}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
