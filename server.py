# server.py
import asyncio
import json
import logging
import uuid
import websockets
from websockets.exceptions import ConnectionClosedOK, ConnectionClosedError
import time # For potential future use (e.g., last seen time)

# --- Configuration ---
SERVER_HOST = "localhost"
SERVER_PORT = 8765

# --- Logging Setup ---
logging.basicConfig(
    level=logging.DEBUG, # Lower level for more detailed info during dev
    format='%(asctime)s %(levelname)s: [Server] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# --- Server State ---
clients = {}  # Dictionary to store client_id: websocket_connection
# Example structure for clients:
# clients = { "client_id_1": {"ws": websocket_object, "peer_id": "client_id_2", "last_pong": time.time()}, ... }

pairings = {} # Dictionary to store client_id -> peer_id mapping for quick lookup
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
    clients[client_id] = {
        "ws": ws,
        "peer_id": None # Initially unpaired
        # "last_pong": time.time() # Add in Stage 5
    }
    logger.info(f"Client {client_id} connected from {ws.remote_address}")
    await send_json(ws, {"type": "your_id", "id": client_id})
    return client_id

def unregister(client_id):
    """Unregisters a client upon disconnection."""
    if client_id in clients:
        client_data = clients.pop(client_id) # Remove and get client data object
        ws = client_data.get("ws")
        peer_id = client_data.get("peer_id")

        # Clean up pairing state (Stage 2 - Server side only)
        if peer_id:
            logger.info(f"Client {client_id} disconnected, removing server-side pairing with {peer_id}")
            # Remove from pairings dictionary
            pairings.pop(client_id, None)
            pairings.pop(peer_id, None)
            # Crucially for Stage 2, we DO NOT notify the peer or clear their peer_id yet.
            # That happens in Stage 5.

        logger.info(f"Client {client_id} disconnected ({ws.remote_address if ws else 'unknown address'}). Remaining clients: {len(clients)}")
    else:
        # This might happen if registration failed partially or if called multiple times
        logger.warning(f"Attempted to unregister non-existent client ID: {client_id}")

async def handle_pair_request(client_id, target_id):
    """Handles a pairing request from a client."""
    requester_data = clients.get(client_id)
    target_data = clients.get(target_id)
    ws_requester = requester_data["ws"]

    # Validation checks
    if not target_data:
        await send_json(ws_requester, {"type": "error", "message": "Target client not found"})
        return
    if requester_data.get("peer_id"):
        await send_json(ws_requester, {"type": "error", "message": "You are already paired"})
        return
    if target_data.get("peer_id"):
        await send_json(ws_requester, {"type": "error", "message": "Target client is already paired"})
        return

    # Update state
    requester_data["peer_id"] = target_id
    target_data["peer_id"] = client_id
    pairings[client_id] = target_id
    pairings[target_id] = client_id
    logger.info(f"Pairing successful: {client_id} <-> {target_id}")

    # Send confirmation to both clients
    ws_target = target_data["ws"]
    await send_json(ws_requester, {"type": "paired", "peer_id": target_id, "initiator": True})
    await send_json(ws_target, {"type": "paired", "peer_id": client_id, "initiator": False})

async def connection_handler(ws, path=None):
    """Handles a new WebSocket connection."""
    client_id = None
    try:
        client_id = await register(ws)
        # Keep the connection open and listen for messages (Stage 1: just listen for close)
        async for raw_message in ws:
            try:
                message_data = json.loads(raw_message)
                msg_type = message_data.get("type")
                logger.debug(f"Received from {client_id}: type={msg_type}, data={message_data}")

                if msg_type == "pair_request":
                    target_id = message_data.get("target_id")
                    if target_id:
                        await handle_pair_request(client_id, target_id)
                    else:
                        logger.warning(f"Received pair_request from {client_id} without target_id.")
                else:
                    logger.warning(f"Received unhandled message type '{msg_type}' from {client_id}")
            except json.JSONDecodeError:
                logger.error(f"Failed to decode JSON message from {client_id}: {raw_message[:200]}")
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
    # Explicitly disable ping_interval and set a large close_timeout to prevent premature disconnections
    server = await websockets.serve(
        connection_handler, 
        SERVER_HOST, 
        SERVER_PORT, 
        ping_interval=None,
        close_timeout=10
    )
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