# server.py
import asyncio
import json
import logging
import uuid
import websockets
from websockets.exceptions import ConnectionClosedOK, ConnectionClosedError
import time # Stage 5: For ping/pong timeouts
from typing import Dict, Any

# --- Configuration ---
SERVER_HOST = "localhost"
SERVER_PORT = 8765
PING_INTERVAL = 30  # seconds (Stage 5)
PING_TIMEOUT = 45   # seconds (must be > PING_INTERVAL) (Stage 5)
if PING_TIMEOUT <= PING_INTERVAL:
    raise ValueError("PING_TIMEOUT must be greater than PING_INTERVAL")

# --- Logging Setup ---
logging.basicConfig(
    level=logging.DEBUG, # Lower level for more detailed info during dev
    format='%(asctime)s %(levelname)s: [Server] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# --- Server State ---
clients: Dict[str, Dict[str, Any]] = {}  # Dictionary to store client_id: {ws, peer_id, ...}
# Example structure for clients (Stage 5):
# clients = { "client_id_1": {"ws": websocket_object, "peer_id": "client_id_2", "last_pong": time.time()}, ... }

pairings: Dict[str, str] = {} # Dictionary to store client_id -> peer_id mapping for quick lookup
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
        "ws": ws, # WebSocket connection object
        "peer_id": None, # Initially unpaired
        "last_pong_time": time.time() # Stage 5: Initialize pong time
     }
    logger.info(f"Client {client_id} connected from {ws.remote_address}")
    await send_json(ws, {"type": "your_id", "id": client_id})
    return client_id

def unregister(client_id):
    """Unregisters a client upon disconnection."""
    if client_id in clients:
        client_data = clients.get(client_id) # Get client data *before* removing
        ws = client_data.get("ws")
        peer_id = client_data.get("peer_id")

        # Clean up pairing state and notify peer
        if peer_id:
            logger.info(f"Client {client_id} disconnected, removing pairing with {peer_id}")
            # Remove from pairings dictionary (both ways)
            pairings.pop(client_id, None)
            pairings.pop(peer_id, None)

            # Notify the peer *if they still exist*
            peer_data = clients.get(peer_id)
            if peer_data:
                peer_ws = peer_data.get("ws")
                # Update peer's state in the clients dictionary
                peer_data["peer_id"] = None
                if peer_ws:
                    # Send notification asynchronously
                    asyncio.create_task(send_json(
                        peer_ws,
                        {"type": "peer_disconnected", "peer_id": client_id}
                    ))
                    logger.info(f"Notified peer {peer_id} about disconnection of {client_id}")
                else:
                    logger.info(f"Peer {peer_id} was already disconnected, cannot notify.")

        logger.info(f"Client {client_id} disconnected ({ws.remote_address if ws else 'unknown address'}). Remaining clients: {len(clients)}")
        # Now remove the client itself
        del clients[client_id]
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

async def handle_message(client_id, target_id, content):
    """Handles message forwarding between paired clients."""
    # Get source client data
    source_data = clients.get(client_id)
    # Get target client data
    target_data = clients.get(target_id)
    
    # Source websocket for error responses
    ws_source = source_data["ws"]
    
    # Validation checks
    if not target_data:
        await send_json(ws_source, {"type": "error", "message": "Target client not found"})
        return
        
    # Check if clients are paired with each other
    if source_data.get("peer_id") != target_id or target_data.get("peer_id") != client_id:
        await send_json(ws_source, {"type": "error", "message": "You are not paired with this client"})
        return
    
    # Get target websocket
    ws_target = target_data["ws"]
    
    # Forward the message to the target client
    await send_json(ws_target, {
        "type": "message",
        "from": client_id,
        "content": content
    })
    
    logger.debug(f"Message forwarded from {client_id} to {target_id}")

async def relay_signaling_message(sender_id: str, message_data: dict):
    """Relays WebRTC signaling messages (offer, answer, candidate) to the peer."""
    peer_id = pairings.get(sender_id)
    if not peer_id:
        logger.warning(f"Client {sender_id} tried to relay signaling message but has no peer.")
        # Optionally send an error back to sender_id
        # ws_sender = clients.get(sender_id, {}).get("ws")
        # if ws_sender:
        #     await send_json(ws_sender, {"type": "error", "message": "Cannot relay message: not paired"})
        return

    peer_data = clients.get(peer_id)
    if not peer_data or not peer_data.get("ws"):
        logger.warning(f"Cannot relay signaling message to peer {peer_id}: Peer not found or disconnected.")
        return

    peer_ws = peer_data["ws"]
    msg_type = message_data.get("type")
    logger.info(f"Relaying '{msg_type}' from {sender_id} to {peer_id}")

    # Add a marker so client knows it's from the peer via the server
    message_data["from_peer"] = True
    await send_json(peer_ws, message_data)

# --- Stage 5: Ping/Pong Keepalive Task ---
async def periodic_pinger():
    """Periodically sends pings to clients and disconnects unresponsive ones."""
    while True:
        await asyncio.sleep(PING_INTERVAL)
        current_time = time.time()
        clients_to_disconnect = []

        # Iterate over a copy because we might modify the dict during iteration indirectly
        for client_id, client_data in list(clients.items()):
            ws = client_data.get("ws")
            last_pong = client_data.get("last_pong_time", 0)

            if current_time - last_pong > PING_TIMEOUT:
                logger.warning(f"Client {client_id} timed out (no pong received). Closing connection.")
                clients_to_disconnect.append((client_id, ws))
                continue # Don't try to ping a timed-out client

            if ws:
                try:
                    logger.debug(f"Sending ping to {client_id}")
                    await send_json(ws, {"type": "ping"})
                except ConnectionClosedError:
                    logger.warning(f"Client {client_id} connection closed before ping could be sent.")
                    # No need to add to disconnect list, finally block will handle it
                except Exception as e:
                    logger.error(f"Error sending ping to {client_id}: {e}", exc_info=True)

        for client_id, ws in clients_to_disconnect:
            await ws.close() # Closing triggers the finally block in connection_handler

async def connection_handler(ws, path=None):
    """Handles a new WebSocket connection."""
    client_id = None
    try:
        client_id = await register(ws)
        # Keep the connection open and listen for messages (Stage 1: just listen for close)
        async for raw_message in ws:
            # Stage 5: Update pong time on *any* message received
            if client_id in clients:
                clients[client_id]["last_pong_time"] = time.time()

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
                elif msg_type == "message": # Application-level message
                    target_id = message_data.get("to")
                    content = message_data.get("content")
                    if target_id and content:
                        await handle_message(client_id, target_id, content)
                    else:
                        logger.warning(f"Received message from {client_id} with missing to/content fields.")
                elif msg_type in ["offer", "answer", "candidate"]: # WebRTC signaling
                    await relay_signaling_message(client_id, message_data)
                elif msg_type == "pong": # Stage 5: Explicitly handle pong (though time update is key)
                    logger.debug(f"Received pong from {client_id}")
                else: # Unknown message type
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
    # Stage 5: Start the periodic pinger task
    ping_task = asyncio.create_task(periodic_pinger())
    logger.info(f"Server starting on ws://{SERVER_HOST}:{SERVER_PORT}...")
    server = None
    try:
        # Use default ping_interval from websockets or set if needed, but our logic handles timeout
        server = await websockets.serve(
            connection_handler,
            SERVER_HOST,
            SERVER_PORT,
            ping_interval=None,  # Disable built-in ping/pong since we're handling it ourselves
            ping_timeout=None,   # Disable built-in ping/pong timeout
            close_timeout=10     # Keep reasonable close timeout
        )
        logger.info(f"Server listening on ws://{SERVER_HOST}:{SERVER_PORT}")

        # Signal that the server is ready (used for testing)
        if ready_queue is not None:
            await ready_queue.put(True)

        # Keep the server running until manually stopped or stop_event is set
        if stop_event:
            # Wait for the stop event
            await stop_event.wait()
        else:
            # Normal operation: keep running indefinitely until Ctrl+C
            await asyncio.Future() # Wait forever

    finally:
        # Clean shutdown
        logger.info("Server shutdown sequence initiated...")
        ping_task.cancel()
        try:
            await ping_task
        except asyncio.CancelledError:
            logger.info("Ping task cancelled.")
        if server:
            await server.wait_closed()
        logger.info("Server shutdown complete.")


if __name__ == "__main__":
    stop = asyncio.Event() # Example for testing stop_event
    try:
        # asyncio.run(main(stop_event=stop)) # Use this if testing stop_event
        asyncio.run(main()) # Normal run
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received, initiating shutdown...")
        # stop.set() # Use this if testing stop_event