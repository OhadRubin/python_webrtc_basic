
Our goal is to implement a WebRTC signaling server and client for establishing peer-to-peer connections. 

We will break down the implementation of the WebRTC signaling server and client into 5 testable stages.

# Server App
- does initial pairing
- periodically validates connection (minimal traffic)

# Client App
- either generates an api key, or connects to a different client via an api key.
- once connected to a different client, it can send messages to the other client via WebRTC.

"Testable" means we can run the code after each stage and verify specific functionality works before moving on.


---

**Stage 1: Basic Server Connection and Client ID Assignment** (DONE!)

*   **Goal:** Verify the server can start, clients can connect via WebSocket, and each client receives a unique ID from the server. Test basic disconnect handling on the server.
*   **Server Implementation (`server.py`):**
    *   Implement imports, logging setup, configuration constants (`SERVER_HOST`, `SERVER_PORT`).
    *   Initialize server state (`clients` dictionary).
    *   Implement `send_json` function.
    *   Implement `register` function to assign IDs and send `"your_id"` message.
    *   Implement a *basic* `unregister` function (just logs disconnect and removes from `clients`).
    *   Implement `connection_handler` to call `register` on connection and `unregister` on disconnection (using `try/finally`). Handle basic `ConnectionClosed` exceptions.
    *   Implement `main` function to start the server (`websockets.serve`).
    *   Implement the main execution block (`if __name__ == "__main__":`).
*   **Client Implementation (`client.py`):**
    *   Implement imports (`asyncio`, `json`, `logging`, `websockets`).
    *   Implement logging setup, `SERVER_URL` constant.
    *   Initialize `websocket` and `my_id` globals to `None`.
    *   Implement `handle_server_message` function to *only* handle the `"your_id"` message type for now (print the ID). Add basic error handling for JSON parsing.
    *   Implement `main` function:
        *   Connect to the server (`websockets.connect`).
        *   Assign the connection to the global `websocket`.
        *   Implement a simple listener loop (`async for message in websocket:`) that calls `handle_server_message`.
        *   Add basic `try/except/finally` for connection errors and cleanup (closing websocket).
    *   Implement the main execution block (`if __name__ == "__main__":`).
*   **Deliverable:**
    *   A running `server.py` that accepts WebSocket connections.
    *   A running `client.py` that connects to the server.
*   **Test:**
    1.  Run `server.py`. Verify it logs "Server starting...".
    2.  Run `client.py`. Verify it logs "Connecting..." and then "Connected...".
    3.  Verify the client prints `*** Your Client ID: <some_uuid> ***`.
    4.  Verify the server logs "Client <some_uuid> connected...".
    5.  Stop the client (Ctrl+C). Verify the client logs shutdown messages.
    6.  Verify the server logs "Client <some_uuid> disconnected.".
    7.  Repeat steps 2-6 with a second client instance simultaneously to ensure unique IDs are assigned.

---

**Stage 2: Server-Side Pairing Logic and Client Pairing Request**

*   **Goal:** Implement the server logic to handle pairing requests between two clients. Clients should be able to request pairing and receive confirmation or errors.
*   **Server Implementation (`server.py`):**
    *   Initialize `pairings` dictionary.
    *   Implement `handle_pair_request` function:
        *   Checks if clients exist and are unpaired.
        *   Updates `clients` and `pairings` state.
        *   Sends `"paired"` message to both clients (with `initiator` flag).
        *   Sends `"error"` message back to the requester on failure (target not found, already paired).
    *   Update `connection_handler` to parse incoming JSON messages and route `"pair_request"` messages to `handle_pair_request`. Add basic handling for unknown message types and JSON errors.
    *   Update `unregister` to remove the client from `pairings` and clear the `peer_id` in the `clients` dictionary for the disconnecting client *only* (peer notification comes later).
*   **Client Implementation (`client.py`):**
    *   Initialize `peer_id` global to `None`.
    *   Implement `send_ws_message` function to send JSON data to the server.
    *   Implement `user_input_handler` function:
        *   Uses `asyncio.get_event_loop().run_in_executor` to get non-blocking input.
        *   If `peer_id` is `None`, treat input as a target ID and call `send_ws_message` with a `{"type": "pair_request", "target_id": cmd}` payload.
        *   (Ignore message sending for now).
    *   Update `handle_server_message` to handle:
        *   `"paired"`: Store the `peer_id`, store the `is_initiator` flag (maybe just log it for now), print confirmation.
        *   `"error"`: Print the error message from the server.
    *   Update `main` function to run the `user_input_handler` concurrently with the WebSocket listener using `asyncio.gather` or `asyncio.wait`.
*   **Deliverable:**
    *   Server can manage pairing state.
    *   Clients can request pairing by entering the target ID.
    *   Clients receive confirmation (`"paired"`) or error messages.
*   **Test:**
    1.  Run `server.py`.
    2.  Run Client A. Note its ID (e.g., `ID_A`).
    3.  Run Client B. Note its ID (e.g., `ID_B`).
    4.  In Client A's terminal, enter `ID_B`.
    5.  Verify Client A prints "*** Paired with ID_B! ... ***".
    6.  Verify Client B prints "*** Paired with ID_A! ... ***".
    7.  Verify the server logs the successful pairing.
    8.  Try pairing Client A with `ID_B` again. Verify Client A prints a server error ("already paired").
    9.  Start Client C. Try pairing Client A with Client C's ID. Verify Client A prints a server error ("already paired").
    10. Try pairing Client C with a non-existent ID. Verify Client C prints a server error ("Target client not found").
****
---

**Stage 3: WebRTC SDP Offer/Answer Exchange via Signaling**

*   **Goal:** Implement the signaling part of the WebRTC handshake. The initiating client sends an offer, the peer receives it, sends an answer, and the initiator receives it, all relayed through the server.
*   **Server Implementation (`server.py`):**
    *   Implement `relay_message` function to forward messages (`"offer"`, `"answer"`) to the correct peer based on the `pairings` dictionary. Include the `"from_peer": True` flag. Log relays or warnings if the peer isn't found.
    *   Update `connection_handler` to route `"offer"` and `"answer"` message types to `relay_message`.
*   **Client Implementation (`client.py`):**
    *   Add `aiortc` imports (`RTCPeerConnection`, `RTCSessionDescription`, etc.).
    *   Define `STUN_SERVER` constant.
    *   Initialize global `pc = RTCPeerConnection(...)` configured with the STUN server.
    *   Implement `start_webrtc(is_initiator)` function:
        *   If `is_initiator`: Create offer (`pc.createOffer`), set local description (`pc.setLocalDescription`), send `"offer"` message via `send_ws_message`.
        *   If not `is_initiator`: Log waiting message (offer comes via WebSocket).
    *   Update `handle_server_message`:
        *   In `"paired"` handler: Call `await start_webrtc(is_initiator)`.
        *   Add handler for `"offer"` (if `from_peer` is true):
            *   Create `RTCSessionDescription` from received SDP.
            *   Set remote description (`pc.setRemoteDescription`).
            *   Create answer (`pc.createAnswer`).
            *   Set local description (`pc.setLocalDescription`).
            *   Send `"answer"` message via `send_ws_message`.
        *   Add handler for `"answer"` (if `from_peer` is true):
            *   Create `RTCSessionDescription` from received SDP.
            *   Set remote description (`pc.setRemoteDescription`).
    *   Add basic `@pc.on("iceconnectionstatechange")` and `@pc.on("connectionstatechange")` handlers (just log the state changes for now).
*   **Deliverable:**
    *   Server relays SDP offers and answers between paired clients.
    *   Clients successfully exchange SDP, setting their local and remote descriptions.
*   **Test:**
    1.  Run `server.py`.
    2.  Run Client A and Client B.
    3.  Pair Client A with Client B.
    4.  Verify Client A (initiator) logs: Creating offer, Sending offer.
    5.  Verify Server logs: Relaying offer from A to B.
    6.  Verify Client B logs: Received offer, Creating answer, Sending answer.
    7.  Verify Server logs: Relaying answer from B to A.
    8.  Verify Client A logs: Received answer.
    9.  (Optional) Check `pc.localDescription` and `pc.remoteDescription` on both clients to confirm they are set. Verify connection state logs show transitions (e.g., "new", "checking").

---

**Stage 4: WebRTC ICE Candidate Exchange and Data Channel Setup**

*   **Goal:** Implement the exchange of ICE candidates via the signaling server. Establish the actual peer-to-peer connection and set up the data channel.
*   **Server Implementation (`server.py`):**
    *   Update `relay_message` to also handle the `"candidate"` message type.
*   **Client Implementation (`client.py`):**
    *   Initialize global `data_channel` to `None`.
    *   Implement `@pc.on("icecandidate")` handler: If a candidate is generated, send it via `send_ws_message` in the required dictionary format (`{"type": "candidate", "candidate": {...}}`).
    *   Implement `@pc.on("datachannel")` handler: Assign the received channel to the global `data_channel`, log it, and call `setup_datachannel_handlers`.
    *   Implement `setup_datachannel_handlers` function: Define and register `@data_channel.on("open")`, `@data_channel.on("close")`, and `@data_channel.on("message")` handlers (print messages for now).
    *   Update `start_webrtc`: If `is_initiator`, create the data channel (`pc.createDataChannel("chat")`), assign it to `data_channel`, and call `setup_datachannel_handlers`.
    *   Update `handle_server_message`: Add handler for `"candidate"` (if `from_peer` is true):
        *   Parse the candidate data.
        *   Create `RTCIceCandidate` object.
        *   Add candidate using `pc.addIceCandidate`. Handle potential errors (e.g., incomplete data).
    *   Update `@pc.on("connectionstatechange")` log to specifically look for "connected".
*   **Deliverable:**
    *   Server relays ICE candidates.
    *   Clients exchange candidates and add them to their `RTCPeerConnection`.
    *   WebRTC connection state should ideally reach "connected".
    *   Data channel should be established and its "open" event should fire on both clients.
*   **Test:**
    1.  Run `server.py`.
    2.  Run Client A and Client B.
    3.  Pair Client A with Client B.
    4.  Verify SDP exchange happens as in Step 3.
    5.  Verify both clients log sending ICE candidates.
    6.  Verify server logs relaying candidates between A and B.
    7.  Verify both clients log receiving and adding ICE candidates.
    8.  Verify both clients log connection state changes, eventually reaching `Peer connection state is connected`.
    9.  Verify both clients print "*** Data channel opened! ... ***".

---

**Stage 5: Data Channel Communication, Ping/Pong, and Disconnect Handling**

*   **Goal:** Enable message sending over the established data channel. Implement server keepalives (ping/pong) and robust peer disconnection notification.
*   **Server Implementation (`server.py`):**
    *   Implement `periodic_pinger` function:
        *   Periodically sleep (`PING_INTERVAL`).
        *   Iterate through clients.
        *   Check `last_pong` time against `current_time` and `PING_TIMEOUT`.
        *   If timed out, log warning, close websocket (`await ws.close()`), add to a list (or let `finally` handle unregister).
        *   If not timed out, send `{"type": "ping"}`.
    *   Update `connection_handler`:
        *   On *any* message received, update `clients[client_id]["last_pong"] = time.time()`.
        *   Handle incoming `"pong"` messages explicitly (can just `pass` as time is updated anyway).
    *   Update `unregister`: When a client disconnects, if it was paired, find the peer, set `peer["peer_id"] = None`, remove peer from `pairings`, and send `{"type": "peer_disconnected"}` to the peer's websocket.
    *   Update `main`: Create and run `periodic_pinger` as an `asyncio` task, ensuring it's cancelled on server shutdown.
*   **Client Implementation (`client.py`):**
    *   Update `user_input_handler`:
        *   If `data_channel` exists and `data_channel.readyState == "open"`, send the user's input using `data_channel.send(cmd)`.
        *   Add print statements for states where sending isn't possible (e.g., "Waiting for data channel...").
    *   Update `setup_datachannel_handlers`: Make the `@data_channel.on("message")` handler print `< Peer: message` and reprint the `> ` prompt correctly.
    *   Update `handle_server_message`:
        *   Add handler for `"ping"`: Call `send_ws_message({"type": "pong"})`.
        *   Add handler for `"peer_disconnected"`:
            *   Print notification.
            *   Set `peer_id = None`.
            *   Close the `pc` (`await pc.close()`).
            *   **Crucially:** Re-create `pc = RTCPeerConnection(...)` and reset `data_channel = None` to allow for a new connection attempt. Print "Ready for new connection.".
    *   Refine `finally` blocks in `main` for robust cleanup of `pc` and `websocket`.
*   **Deliverable:**
    *   A fully functional peer-to-peer text chat application using WebRTC data channels.
    *   Server maintains connection health via ping/pong and disconnects inactive clients.
    *   Clients are notified when their peer disconnects and reset their state correctly.
*   **Test:**
    1.  Run `server.py`. Run Client A and Client B. Pair them.
    2.  Verify data channel opens.
    3.  In Client A, type "Hello B!" and press Enter. Verify Client B prints `< Peer: Hello B!`.
    4.  In Client B, type "Hi A!" and press Enter. Verify Client A prints `< Peer: Hi A!`.
    5.  Leave clients idle for longer than `PING_INTERVAL`. Verify server logs pings and clients stay connected (implicitly testing pong response).
    6.  Stop Client B (Ctrl+C).
    7.  Verify server logs Client B disconnecting and logs notifying Client A.
    8.  Verify Client A prints `*** Peer <ID_B> disconnected. ***` and `Ready for new connection.`.
    9.  Run Client C. Note its ID (`ID_C`).
    10. In Client A, enter `ID_C`. Verify they pair successfully and can exchange messages.
    11. (Timeout Test): Modify `PING_TIMEOUT` to be short (e.g., 5s), stop a client *without* sending pong (e.g., by patching the client to ignore ping), and verify the server disconnects it after `PING_INTERVAL + PING_TIMEOUT`.