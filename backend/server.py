from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import os
from dotenv import load_dotenv
from typing import Optional, List, Dict
import json
import re
import uuid
from datetime import datetime
import boto3
from botocore.exceptions import ClientError
from groq import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    Groq,
    RateLimitError,
)
from context import prompt
from guardrails import check_input, check_output

# Load environment variables
load_dotenv()

app = FastAPI()

# Configure CORS
origins = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# LLM: Groq, bring-your-own-key. Visitors send their own key per request in the
# X-Groq-Api-Key header; the server never stores or logs it and has no key of its own.
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

# Memory storage configuration
USE_S3 = os.getenv("USE_S3", "false").lower() == "true"
S3_BUCKET = os.getenv("S3_BUCKET", "")
MEMORY_DIR = os.getenv("MEMORY_DIR", "../memory")

# Initialize S3 client if needed
if USE_S3:
    s3_client = boto3.client("s3")


# Request/Response models
class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)  # cap input size
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    response: str
    session_id: str


class Message(BaseModel):
    role: str
    content: str
    timestamp: str


# Memory management functions
def get_memory_path(session_id: str) -> str:
    # session_id comes from the client; block path traversal like "../x"
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", session_id):
        raise HTTPException(status_code=400, detail="Invalid session_id")
    return f"{session_id}.json"


def load_conversation(session_id: str) -> List[Dict]:
    """Load conversation history from storage"""
    if USE_S3:
        try:
            response = s3_client.get_object(
                Bucket=S3_BUCKET, Key=get_memory_path(session_id)
            )
            return json.loads(response["Body"].read().decode("utf-8"))
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                return []
            raise
    else:
        # Local file storage
        file_path = os.path.join(MEMORY_DIR, get_memory_path(session_id))
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return []


def save_conversation(session_id: str, messages: List[Dict]):
    """Save conversation history to storage"""
    if USE_S3:
        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=get_memory_path(session_id),
            Body=json.dumps(messages, indent=2),
            ContentType="application/json",
        )
    else:
        # Local file storage
        os.makedirs(MEMORY_DIR, exist_ok=True)
        file_path = os.path.join(MEMORY_DIR, get_memory_path(session_id))
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(messages, f, indent=2, ensure_ascii=False)


def call_llm(api_key: str, conversation: List[Dict], user_message: str) -> str:
    """Call Groq with the visitor's own API key and the conversation history"""

    # System prompt first, then recent history (last 6 exchanges), then the new message.
    # Groq's free tier counts prompt + max_tokens against a per-minute budget, so keep both small.
    messages = [{"role": "system", "content": prompt()}]
    for msg in conversation[-12:]:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_message})

    extra = {}
    if GROQ_MODEL.startswith("openai/gpt-oss"):
        extra["extra_body"] = {"reasoning_effort": "low"}  # faster, fewer hidden tokens

    try:
        # Client is built per request from the visitor's key: nothing is shared or cached.
        # No retries and a 24s timeout: API Gateway cuts requests at 30s, so fail fast with a
        # clear message instead of hanging.
        client = Groq(api_key=api_key, max_retries=0, timeout=24.0)
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
            max_tokens=700,
            temperature=0.7,
            **extra,
        )
        return response.choices[0].message.content or ""

    # Provider errors can include the organization ID: log them, never return them
    except AuthenticationError as e:
        print(f"Groq rejected the API key: {e}")
        raise HTTPException(status_code=401, detail="Groq rejected your API key")
    except RateLimitError as e:
        print(f"Groq rate limit: {e}")
        raise HTTPException(
            status_code=429, detail="Your Groq key hit its rate limit, try again in a few seconds"
        )
    except (APITimeoutError, APIConnectionError) as e:
        print(f"Groq timeout/connection error: {e}")
        raise HTTPException(status_code=504, detail="The model took too long to respond")
    except APIStatusError as e:
        print(f"Groq API error {e.status_code}: {e}")
        raise HTTPException(status_code=502, detail="The model request failed")


@app.get("/")
async def root():
    return {
        "message": "AI Digital Twin API (Powered by Groq, bring your own key)",
        "memory_enabled": True,
        "storage": "S3" if USE_S3 else "local",
        "ai_model": GROQ_MODEL,
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy", "use_s3": USE_S3, "model": GROQ_MODEL}


@app.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    x_groq_api_key: Optional[str] = Header(default=None),
):
    # Cheap check before any work: the key must look like a Groq key
    api_key = (x_groq_api_key or "").strip()
    if not api_key.startswith("gsk_"):
        raise HTTPException(status_code=401, detail="A Groq API key is required")

    try:
        # Generate session ID if not provided
        session_id = request.session_id or str(uuid.uuid4())
        get_memory_path(session_id)  # rejects malformed session IDs (400)

        # Guardrail: block prompt injection / dangerous requests before any LLM call.
        # Blocked messages are not saved, so they never enter the model's context.
        blocked_reply = check_input(request.message)
        if blocked_reply:
            return ChatResponse(response=blocked_reply, session_id=session_id)

        # Load conversation history
        conversation = load_conversation(session_id)

        # Call the LLM with the visitor's own key
        assistant_response = check_output(
            call_llm(api_key, conversation, request.message)
        )

        # Update conversation history
        conversation.append(
            {
                "role": "user",
                "content": request.message,
                "timestamp": datetime.now().isoformat(),
            }
        )
        conversation.append(
            {
                "role": "assistant",
                "content": assistant_response,
                "timestamp": datetime.now().isoformat(),
            }
        )

        # Save conversation
        save_conversation(session_id, conversation)

        return ChatResponse(response=assistant_response, session_id=session_id)

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in chat endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/conversation/{session_id}")
async def get_conversation(session_id: str):
    """Retrieve conversation history"""
    try:
        conversation = load_conversation(session_id)
        return {"session_id": session_id, "messages": conversation}
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in get_conversation: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
