# server.py
import asyncio
import json
import logging
import uuid
import websockets
from websockets.exceptions import ConnectionClosedOK, ConnectionClosedError

# --- Configuration ---
SERVER_HOST = "localhost"
SERVER_PORT = 8765

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: [Server] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# --- Server State ---
clients = {}  # Dictionary to store client_id: websocket_connection

# --- Helper Functions ---
async def send_json(ws, data):
    """Sends JSON data over a WebSocket connection."""
    try:
        await ws.send(json.dumps(data))
    except ConnectionClosedError:
        logger.warning(f"Attempted to send to already closed connection {ws.remote_address}")
    except Exception as e:
        logger.error(f"Error sending JSON to {ws.remote_address}: {e}", exc_info=True)

# --- Core Logic ---
async def register(ws):
    """Registers a new client, assigns a unique ID, and notifies the client."""
    client_id = str(uuid.uuid4())
    clients[client_id] = ws
    logger.info(f"Client {client_id} connected from {ws.remote_address}")
    await send_json(ws, {"type": "your_id", "id": client_id})
    return client_id

def unregister(client_id):
    """Unregisters a client upon disconnection."""
    if client_id in clients:
        ws = clients.pop(client_id) # Remove and get ws object
        logger.info(f"Client {client_id} disconnected ({ws.remote_address}). Remaining clients: {len(clients)}")
    else:
        # This might happen if registration failed partially or if called multiple times
        logger.warning(f"Attempted to unregister non-existent client ID: {client_id}")

async def connection_handler(ws, path=None):
    """Handles a new WebSocket connection."""
    client_id = None
    try:
        client_id = await register(ws)
        # Keep the connection open and listen for messages (Stage 1: just listen for close)
        async for message in ws:
            # In Stage 1, clients don't send meaningful messages yet.
            # We just need the loop to detect disconnection.
            # Optionally log unexpected messages:
            logger.warning(f"Received unexpected message from {client_id}: {message[:100]}...")
            # In later stages, message parsing and handling will happen here.
            pass
    except ConnectionClosedOK:
        logger.info(f"Client {client_id or 'unknown'} closed connection cleanly.")
    except ConnectionClosedError as e:
        logger.warning(f"Client {client_id or 'unknown'} connection closed unexpectedly: {e.code} {e.reason}")
    except Exception as e:
        logger.error(f"Error during connection handling for {client_id or 'unknown'}: {e}", exc_info=True)
    finally:
        # Ensure cleanup happens regardless of how the connection ends
        if client_id is not None:
            unregister(client_id)

# --- Main Execution ---
async def main(ready_queue=None, stop_event=None):
    """Starts the WebSocket server."""
    logger.info(f"Server starting on ws://{SERVER_HOST}:{SERVER_PORT}...")
    server = await websockets.serve(connection_handler, SERVER_HOST, SERVER_PORT)
    logger.info(f"Server listening on ws://{SERVER_HOST}:{SERVER_PORT}")
    
    # Signal that the server is ready (used for testing)
    if ready_queue is not None:
        await ready_queue.put(True)
    
    # Keep the server running until manually stopped or stop_event is set
    if stop_event:
        # When using stop_event, wait for it to be set
        while not stop_event.is_set():
            await asyncio.sleep(0.1)
        # Clean shutdown when stop_event is set
        server.close()
        await server.wait_closed()
        logger.info("Server shutdown gracefully.")
    else:
        # Normal operation: keep running indefinitely
        await server.wait_closed()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server shutting down...")