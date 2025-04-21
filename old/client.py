#  client.py

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
