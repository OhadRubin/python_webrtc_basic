# pip install websockets aiortc asyncio

import asyncio
import json
import logging
import uuid
import time
import websockets

logging.basicConfig(level=logging.INFO)

# --- Configuration ---
SERVER_HOST = "0.0.0.0"  # Listen on all interfaces
SERVER_PORT = 8765
PING_INTERVAL = 30  # Seconds
PING_TIMEOUT = 10   # Seconds

# --- Server State ---
clients = {}  # {client_id: {"ws": websocket, "last_pong": timestamp, "peer_id": peer_id}}
pairings = {} # {client_id: peer_id} # For quick lookup during signaling

async def send_json(websocket, data):
    """Safely send JSON data over WebSocket."""
    try:
        await websocket.send(json.dumps(data))
    except websockets.exceptions.ConnectionClosed:
        logging.info("Failed to send: Connection closed.")

async def register(websocket):
    """Register a new client, assign ID, and start ping task."""
    client_id = str(uuid.uuid4())
    clients[client_id] = {"ws": websocket, "last_pong": time.time(), "peer_id": None}
    logging.info(f"Client {client_id} connected from {websocket.remote_address}")
    await send_json(websocket, {"type": "your_id", "id": client_id})
    return client_id

async def unregister(client_id):
    """Unregister a client and notify its peer if paired."""
    logging.info(f"Client {client_id} disconnected.")
    client_info = clients.pop(client_id, None)
    if client_info and client_info["peer_id"]:
        peer_id = client_info["peer_id"]
        pairings.pop(client_id, None)
        peer_info = clients.get(peer_id)
        if peer_info:
            peer_info["peer_id"] = None # Unpair the peer
            pairings.pop(peer_id, None)
            logging.info(f"Notifying peer {peer_id} of disconnection.")
            await send_json(peer_info["ws"], {"type": "peer_disconnected"})

async def handle_pair_request(client_id, target_id):
    """Attempt to pair two clients."""
    client_info = clients.get(client_id)
    target_info = clients.get(target_id)

    if not client_info or not target_info:
        await send_json(client_info["ws"], {"type": "error", "message": "Target client not found."})
        return

    if client_info.get("peer_id") or target_info.get("peer_id"):
        await send_json(client_info["ws"], {"type": "error", "message": "One or both clients already paired."})
        return

    # Establish pairing
    client_info["peer_id"] = target_id
    target_info["peer_id"] = client_id
    pairings[client_id] = target_id
    pairings[target_id] = client_id

    logging.info(f"Pairing successful: {client_id} <-> {target_id}")
    await send_json(client_info["ws"], {"type": "paired", "peer_id": target_id, "initiator": True})
    await send_json(target_info["ws"], {"type": "paired", "peer_id": client_id, "initiator": False})

async def relay_message(sender_id, message_data):
    """Relay WebRTC signaling messages (offer, answer, candidate) to the peer."""
    peer_id = pairings.get(sender_id)
    if peer_id and peer_id in clients:
        peer_ws = clients[peer_id]["ws"]
        message_data["from_peer"] = True # Mark message as relayed
        logging.debug(f"Relaying {message_data.get('type')} from {sender_id} to {peer_id}")
        await send_json(peer_ws, message_data)
    else:
        logging.warning(f"Cannot relay message from {sender_id}: Peer not found or not connected.")

async def connection_handler(websocket, path):
    """Main handler for WebSocket connections."""
    client_id = await register(websocket)
    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                msg_type = data.get("type")
                logging.debug(f"Received from {client_id}: {data}")

                clients[client_id]["last_pong"] = time.time() # Treat any message as activity

                if msg_type == "pair_request":
                    await handle_pair_request(client_id, data.get("target_id"))
                elif msg_type in ["offer", "answer", "candidate"]:
                    await relay_message(client_id, data)
                elif msg_type == "pong":
                    pass # Already updated last_pong time
                else:
                    logging.warning(f"Unknown message type from {client_id}: {msg_type}")

            except json.JSONDecodeError:
                logging.error(f"Invalid JSON received from {client_id}")
            except Exception as e:
                logging.error(f"Error processing message from {client_id}: {e}", exc_info=True)

    except websockets.exceptions.ConnectionClosedOK:
        logging.info(f"Connection closed normally for {client_id}.")
    except websockets.exceptions.ConnectionClosedError as e:
        logging.warning(f"Connection closed with error for {client_id}: {e}")
    finally:
        await unregister(client_id)

async def periodic_pinger():
    """Periodically sends pings and checks for timeouts."""
    while True:
        await asyncio.sleep(PING_INTERVAL)
        current_time = time.time()
        disconnected_clients = []

        # Create a copy of client IDs to iterate over, as unregister modifies the dict
        client_ids = list(clients.keys())

        for client_id in client_ids:
            if client_id not in clients: # Client might have disconnected during sleep
                continue
            client_info = clients[client_id]
            if current_time - client_info["last_pong"] > PING_INTERVAL + PING_TIMEOUT:
                logging.warning(f"Client {client_id} timed out. Disconnecting.")
                disconnected_clients.append(client_id)
                # Close the connection from server-side
                await client_info["ws"].close(code=1000, reason="Ping timeout")
            else:
                # Send ping
                logging.debug(f"Pinging client {client_id}")
                await send_json(client_info["ws"], {"type": "ping"})

        # Unregister timed-out clients (if not already handled by close)
        # for client_id in disconnected_clients:
        #     if client_id in clients: # Check again in case close handler ran first
        #         await unregister(client_id)


async def main():
    logging.info(f"Starting WebSocket server on {SERVER_HOST}:{SERVER_PORT}")
    ping_task = asyncio.create_task(periodic_pinger())
    server = await websockets.serve(connection_handler, SERVER_HOST, SERVER_PORT)
    await server.wait_closed()
    ping_task.cancel()
    try:
        await ping_task
    except asyncio.CancelledError:
        logging.info("Ping task cancelled.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Server stopped manually.")

# client.py

import asyncio
import json
import logging
import aiortc
import websockets
from aiortc import RTCIceCandidate, RTCPeerConnection, RTCSessionDescription, MediaStreamTrack
from aiortc.contrib.media import MediaPlayer, MediaRelay

logging.basicConfig(level=logging.INFO)
# logging.getLogger("aiortc").setLevel(logging.WARNING) # Reduce aiortc verbosity
# logging.getLogger("websockets").setLevel(logging.WARNING) # Reduce websockets verbosity


# --- Configuration ---
SERVER_URL = "ws://localhost:8765" # Change if server is remote

# --- Client State ---
my_id = None
peer_id = None
websocket = None
pc = None # RTCPeerConnection
data_channel = None

# --- WebRTC Setup ---
# Use Google's public STUN server
STUN_SERVER = "stun:stun.l.google.com:19302"
pc = RTCPeerConnection(iceServers=[aiortc.RTCIceServer(urls=[STUN_SERVER])])

@pc.on("datachannel")
def on_datachannel(channel):
    global data_channel
    logging.info(f"Data channel '{channel.label}' created by remote")
    data_channel = channel
    setup_datachannel_handlers()

@pc.on("iceconnectionstatechange")
async def on_iceconnectionstatechange():
    logging.info(f"ICE connection state is {pc.iceConnectionState}")
    if pc.iceConnectionState == "failed":
        await pc.close()
        logging.error("ICE connection failed")
        # TODO: Add potential cleanup or reconnection logic here

@pc.on("connectionstatechange")
async def on_connectionstatechange():
    logging.info(f"Peer connection state is {pc.connectionState}")
    if pc.connectionState == "failed":
        await pc.close()
        logging.error("Peer connection failed")
    elif pc.connectionState == "closed":
        logging.info("Peer connection closed.")
        # TODO: Reset state for potential new pairing

@pc.on("icecandidate")
async def on_icecandidate(candidate):
    if candidate and websocket and websocket.open:
        logging.debug(f"Sending ICE candidate: {candidate.sdp}")
        await send_ws_message({
            "type": "candidate",
            "candidate": { # aiortc candidate to dict
                 "sdpMid": candidate.sdpMid,
                 "sdpMLineIndex": candidate.sdpMLineIndex,
                 "candidate": candidate.sdp,
            }
        })

def setup_datachannel_handlers():
    global data_channel
    if not data_channel:
        return

    @data_channel.on("open")
    def on_open():
        print("\n*** Data channel opened! You can now send messages. ***")
        print("> ", end="", flush=True) # Prompt for input

    @data_channel.on("close")
    def on_close():
        print("\n*** Data channel closed. ***")

    @data_channel.on("message")
    def on_message(message):
        # Ensure prompt is reprinted after receiving a message
        print(f"\n< Peer: {message}")
        print("> ", end="", flush=True)

async def send_ws_message(data):
    """Send JSON message via WebSocket."""
    if websocket and websocket.open:
        await websocket.send(json.dumps(data))

async def start_webrtc(is_initiator):
    """Initiate or respond to WebRTC connection."""
    global data_channel, pc

    if is_initiator:
        logging.info("Creating data channel 'chat'")
        data_channel = pc.createDataChannel("chat")
        setup_datachannel_handlers()

        logging.info("Creating SDP offer")
        offer = await pc.createOffer()
        await pc.setLocalDescription(offer)
        logging.info("Sending SDP offer to server")
        await send_ws_message({
            "type": "offer",
            "sdp": pc.localDescription.sdp,
            "sdp_type": pc.localDescription.type # 'offer'
        })
    else:
        logging.info("Waiting for SDP offer from peer...")
        # The offer will arrive via WebSocket and be handled by handle_server_message


async def handle_server_message(message):
    """Process messages received from the signaling server."""
    global my_id, peer_id, pc, data_channel
    try:
        data = json.loads(message)
        msg_type = data.get("type")
        logging.debug(f"Server message received: {data}")

        if msg_type == "your_id":
            my_id = data["id"]
            print(f"*** Your Client ID: {my_id} ***")
            print("Enter peer's ID to connect, or wait for connection.")

        elif msg_type == "paired":
            peer_id = data["peer_id"]
            is_initiator = data["initiator"]
            print(f"\n*** Paired with {peer_id}! Starting WebRTC setup... ***")
            await start_webrtc(is_initiator)

        elif msg_type == "offer" and data.get("from_peer"):
            logging.info("Received SDP offer from peer")
            offer = RTCSessionDescription(sdp=data["sdp"], type=data["sdp_type"])
            await pc.setRemoteDescription(offer)

            logging.info("Creating SDP answer")
            answer = await pc.createAnswer()
            await pc.setLocalDescription(answer)
            logging.info("Sending SDP answer to server")
            await send_ws_message({
                "type": "answer",
                "sdp": pc.localDescription.sdp,
                "sdp_type": pc.localDescription.type # 'answer'
            })

        elif msg_type == "answer" and data.get("from_peer"):
            logging.info("Received SDP answer from peer")
            answer = RTCSessionDescription(sdp=data["sdp"], type=data["sdp_type"])
            await pc.setRemoteDescription(answer)

        elif msg_type == "candidate" and data.get("from_peer"):
            ice_cand_data = data.get("candidate")
            if ice_cand_data and ice_cand_data.get("candidate"):
                # Handle slightly different candidate formats if necessary
                # aiortc candidate from dict
                candidate = RTCIceCandidate(
                    sdpMid=ice_cand_data.get("sdpMid"),
                    sdpMLineIndex=ice_cand_data.get("sdpMLineIndex"),
                    sdp=ice_cand_data.get("candidate")
                )
                logging.debug(f"Received ICE candidate from peer: {candidate.sdp}")
                await pc.addIceCandidate(candidate)
            else:
                 logging.warning(f"Received incomplete ICE candidate data: {ice_cand_data}")


        elif msg_type == "peer_disconnected":
            print(f"\n*** Peer {peer_id} disconnected. ***")
            peer_id = None
            if pc and pc.connectionState != "closed":
                await pc.close()
            # Reset PeerConnection for potential new pairing
            pc = RTCPeerConnection(iceServers=[aiortc.RTCIceServer(urls=[STUN_SERVER])])
            data_channel = None # Reset data channel too
            print("Ready for new connection.")


        elif msg_type == "ping":
            logging.debug("Received ping, sending pong.")
            await send_ws_message({"type": "pong"})

        elif msg_type == "error":
            print(f"\n*** Server Error: {data.get('message')} ***")

    except json.JSONDecodeError:
        logging.error("Invalid JSON received from server.")
    except Exception as e:
        logging.error(f"Error handling server message: {e}", exc_info=True)


async def user_input_handler():
    """Handle user commands (pairing, sending messages)."""
    global peer_id, data_channel
    loop = asyncio.get_event_loop()
    while True:
        try:
            # Use run_in_executor to avoid blocking the event loop with input()
            cmd = await loop.run_in_executor(None, input, "> ")
            cmd = cmd.strip()
            if not cmd:
                continue

            if not peer_id and not data_channel: # Not paired yet
                # Assume input is a target ID for pairing
                print(f"Attempting to pair with {cmd}...")
                await send_ws_message({"type": "pair_request", "target_id": cmd})
            elif data_channel and data_channel.readyState == "open": # Paired and channel open
                # Send message via WebRTC
                data_channel.send(cmd)
            elif peer_id and not (data_channel and data_channel.readyState == "open"):
                 print("Waiting for data channel to open...")
            else: # Should not happen?
                 print("Cannot send message - not connected.")

        except (EOFError, KeyboardInterrupt):
            print("\nExiting...")
            break
        except Exception as e:
            logging.error(f"Error in user input handler: {e}", exc_info=True)

async def main():
    global websocket, pc
    uri = SERVER_URL
    logging.info(f"Connecting to signaling server: {uri}")

    try:
        async with websockets.connect(uri) as ws:
            websocket = ws
            print(f"Connected to server {uri}")

            # Run websocket listener and user input concurrently
            listen_task = asyncio.create_task(
                asyncio.gather(*(handle_server_message(msg) async for msg in websocket))
            )
            input_task = asyncio.create_task(user_input_handler())

            # Wait for either task to complete (e.g., disconnection or user exit)
            done, pending = await asyncio.wait(
                [listen_task, input_task],
                return_when=asyncio.FIRST_COMPLETED,
            )

            # Cancel pending tasks
            for task in pending:
                task.cancel()
                try:
                    await task # Allow cleanup
                except asyncio.CancelledError:
                    pass

            logging.info("Tasks finished or cancelled.")

    except (websockets.exceptions.ConnectionClosedError, ConnectionRefusedError) as e:
        print(f"\n*** Connection to server failed: {e} ***")
        logging.error(f"Connection failed: {e}")
    except Exception as e:
         print(f"\n*** An unexpected error occurred: {e} ***")
         logging.error(f"Unexpected error: {e}", exc_info=True)
    finally:
        if pc and pc.connectionState != "closed":
            logging.info("Closing RTCPeerConnection.")
            await pc.close()
        if websocket and websocket.open:
            logging.info("Closing WebSocket connection.")
            await websocket.close()
        logging.info("Client shutdown complete.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nClient stopped manually.")