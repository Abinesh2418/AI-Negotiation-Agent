from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import json
import asyncio
import uuid
from datetime import datetime
import uvicorn
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import custom modules
from models import Product, NegotiationParams, ChatMessage, NegotiationSession
from database import JSONDatabase
from gemini_service import GeminiAIService
from websocket_manager import ConnectionManager

# Initialize FastAPI app
app = FastAPI(
    title=os.getenv("APP_NAME", "NegotiBot AI API"),
    description=os.getenv("APP_DESCRIPTION", "AI-powered marketplace negotiation platform"),
    version=os.getenv("APP_VERSION", "1.0.0"),
    debug=os.getenv("DEBUG", "false").lower() == "true"
)

# CORS middleware
allowed_origins = os.getenv("ALLOWED_ORIGINS", "*")
origins = ["*"] if allowed_origins == "*" else allowed_origins.split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=os.getenv("ENABLE_CORS_CREDENTIALS", "true").lower() == "true",
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files (frontend)
demo_path = Path(__file__).parent.parent / "demo"
if demo_path.exists():
    app.mount("/static", StaticFiles(directory=str(demo_path)), name="static")

# Mount seller interface
seller_path = Path(__file__).parent.parent / "seller-interface"
if seller_path.exists():
    app.mount("/seller", StaticFiles(directory=str(seller_path)), name="seller")

# Initialize services
db = JSONDatabase()
ai_service = GeminiAIService()
manager = ConnectionManager()

# Global storage for active connections and sessions
active_sessions: Dict[str, NegotiationSession] = {}


def serialize_message(message: ChatMessage) -> dict:
    """Convert ChatMessage to JSON-serializable dict"""
    return {
        "id": message.id,
        "session_id": message.session_id,
        "sender": message.sender,
        "content": message.content,
        "timestamp": message.timestamp.isoformat(),
        "sender_type": message.sender_type
    }


@app.on_event("startup")
async def startup_event():
    """Initialize database and services on startup"""
    await db.initialize()
    print("✅ NegotiBot AI Backend started successfully!")


@app.get("/")
async def root():
    """Root endpoint"""
    return {"message": "NegotiBot AI Backend is running!", "version": "1.0.0"}


@app.get("/api/products", response_model=List[Product])
async def get_products():
    """Get all predefined products"""
    try:
        products = await db.get_products()
        return products
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/products/{product_id}", response_model=Product)
async def get_product(product_id: str):
    """Get specific product by ID"""
    try:
        product = await db.get_product(product_id)
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        return product
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/negotiations/start")
async def start_negotiation(params: NegotiationParams):
    """Start a new negotiation session"""
    try:
        # Create new session
        session_id = str(uuid.uuid4())
        session = NegotiationSession(
            id=session_id,
            product_id=params.product_id,
            user_params=params,
            status="active",
            created_at=datetime.now(),
            messages=[]
        )
        
        # Save session
        active_sessions[session_id] = session
        await db.save_session(session)
        
        # Get product details
        product = await db.get_product(params.product_id)
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
            
        return {
            "session_id": session_id,
            "message": "Negotiation session started successfully",
            "product": product
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.websocket("/ws/user/{session_id}")
async def websocket_user_endpoint(websocket: WebSocket, session_id: str):
    """WebSocket endpoint for user (AI agent) side"""
    await manager.connect_user(websocket, session_id)
    try:
        while True:
            # Listen for user messages (manual overrides)
            data = await websocket.receive_text()
            message_data = json.loads(data)
            
            # Process user message
            await handle_user_message(session_id, message_data)
            
    except WebSocketDisconnect:
        manager.disconnect_user(session_id)
        print(f"User disconnected from session: {session_id}")


@app.websocket("/ws/seller/{session_id}")
async def websocket_seller_endpoint(websocket: WebSocket, session_id: str):
    """WebSocket endpoint for seller side"""
    await manager.connect_seller(websocket, session_id)
    try:
        while True:
            # Listen for seller messages
            data = await websocket.receive_text()
            message_data = json.loads(data)
            
            # Process seller message and generate AI response
            await handle_seller_message(session_id, message_data)
            
    except WebSocketDisconnect:
        manager.disconnect_seller(session_id)
        print(f"Seller disconnected from session: {session_id}")


async def handle_user_message(session_id: str, message_data: dict):
    """Handle user override messages"""
    if session_id not in active_sessions:
        return
        
    session = active_sessions[session_id]
    
    # Create message
    message = ChatMessage(
        id=str(uuid.uuid4()),
        session_id=session_id,
        sender="user",
        content=message_data.get("content", ""),
        timestamp=datetime.now(),
        sender_type="override"
    )
    
    # Add to session
    session.messages.append(message)
    
    # Send to seller
    await manager.send_to_seller(session_id, {
        "type": "message",
        "message": serialize_message(message),
        "sender": "buyer"
    })
    
    # Save session
    await db.save_session(session)


async def handle_seller_message(session_id: str, message_data: dict):
    """Handle seller messages and generate AI response"""
    if session_id not in active_sessions:
        return
        
    session = active_sessions[session_id]
    
    # Create seller message
    seller_message = ChatMessage(
        id=str(uuid.uuid4()),
        session_id=session_id,
        sender="seller",
        content=message_data.get("content", ""),
        timestamp=datetime.now(),
        sender_type="human"
    )
    
    # Add to session
    session.messages.append(seller_message)
    
    # Send to user
    await manager.send_to_user(session_id, {
        "type": "message",
        "message": serialize_message(seller_message),
        "sender": "seller"
    })
    
    # Generate AI response
    try:
        ai_response = await ai_service.generate_response(
            session.user_params.approach,
            session.user_params.target_price,
            session.user_params.max_budget,
            session.messages,
            await db.get_product(session.product_id)
        )
        
        # Create AI message
        ai_message = ChatMessage(
            id=str(uuid.uuid4()),
            session_id=session_id,
            sender="ai",
            content=ai_response,
            timestamp=datetime.now(),
            sender_type="ai"
        )
        
        # Add to session
        session.messages.append(ai_message)
        
        # Send AI response to seller (appears as buyer message)
        await manager.send_to_seller(session_id, {
            "type": "message",
            "message": serialize_message(ai_message),
            "sender": "buyer"
        })
        
        # Send AI response to user for monitoring
        await manager.send_to_user(session_id, {
            "type": "ai_response",
            "message": serialize_message(ai_message),
            "sender": "ai"
        })
        
    except Exception as e:
        print(f"Error generating AI response: {e}")
        # Send error to user
        await manager.send_to_user(session_id, {
            "type": "error",
            "message": "Failed to generate AI response"
        })
    
    # Save session
    await db.save_session(session)


@app.get("/api/negotiations/{session_id}")
async def get_negotiation_session(session_id: str):
    """Get negotiation session details"""
    try:
        if session_id in active_sessions:
            session = active_sessions[session_id]
        else:
            session = await db.get_session(session_id)
            
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
            
        return session
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/negotiations/{session_id}/end")
async def end_negotiation(session_id: str, result: dict):
    """End negotiation session with result"""
    try:
        if session_id in active_sessions:
            session = active_sessions[session_id]
            session.status = "completed"
            session.final_price = result.get("final_price")
            session.outcome = result.get("outcome", "unknown")
            session.ended_at = datetime.now()
            
            # Save final session
            await db.save_session(session)
            
            # Notify both parties
            await manager.send_to_user(session_id, {
                "type": "session_ended",
                "result": result
            })
            
            await manager.send_to_seller(session_id, {
                "type": "session_ended", 
                "result": result
            })
            
            # Remove from active sessions
            del active_sessions[session_id]
            
        return {"message": "Negotiation ended successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        reload=os.getenv("RELOAD", "false").lower() == "true",
        log_level=os.getenv("LOG_LEVEL", "info").lower()
    )