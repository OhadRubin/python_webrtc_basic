## Stage 5 Detailed Plan: Data Channel Communication, Ping/Pong, and Disconnect Handling

**Goal:** Enable message sending over the established data channel, implement server keepalives (ping/pong) to ensure connection health, and handle peer disconnections gracefully by notifying the remaining client and allowing it to reset for a new connection.

**Essential Functionality:**

1.  **Data Channel Message Transfer:** Clients can send text messages to their peer via the established WebRTC data channel, and receive/display messages sent by the peer.
2.  **Server Keepalive (Ping/Pong):** The server periodically sends "ping" messages to clients. Clients respond with "pong" messages (or any message suffices) to indicate liveness. The server tracks the last response time.
3.  **Server Timeout Disconnect:** The server disconnects clients that fail to respond within a defined timeout period after a ping.
4.  **Peer Disconnection Notification:** When a client disconnects (cleanly or via timeout), the server notifies the paired peer.
5.  **Client State Reset on Peer Disconnect:** The client receiving the peer disconnection notification cleans up its WebRTC state, resets internal pairing/channel variables, and prepares a fresh `RTCPeerConnection` object, making it ready to pair with a new client.

---

### Implementation Plan (Essential Only)

**Server (`server.py`)**

1.  **Constants:** Define `PING_INTERVAL` (e.g., 30 seconds) and `PING_TIMEOUT` (e.g., 45 seconds - must be > `PING_INTERVAL`). Import `time` and `asyncio`.
2.  **Client State Update:** Modify the `clients` dictionary structure slightly or add a parallel structure to store the `last_pong_time` for each client ID. Initialize it in `register`.
3.  **Update `last_pong_time`:** In `connection_handler`, within the `async for message in websocket:` loop, *before* processing the message type, update the client's `last_pong_time`: `clients[client_id]["last_pong_time"] = time.time()`. This ensures any message from the client resets the timer.
4.  **Handle `"pong"` Message:** Add a case in the message handling logic within `connection_handler` for `{"type": "pong"}`. It doesn't need to do anything specific (`pass`) because the `last_pong_time` was already updated.
5.  **Implement `periodic_pinger` Task:**
    *   Create an `async def periodic_pinger():` function.
    *   Use a `while True:` loop.
    *   Inside the loop:
        *   `await asyncio.sleep(PING_INTERVAL)`
        *   Get `current_time = time.time()`.
        *   Create a list of clients to disconnect: `clients_to_disconnect = []`.
        *   Iterate through a *copy* of the `clients.items()` (to avoid issues if modifying during iteration): `for client_id, client_data in list(clients.items()):`.
        *   Check if `current_time - client_data.get("last_pong_time", 0) > PING_TIMEOUT`.
            *   If true: Log a timeout warning, add `(client_id, client_data["websocket"])` to `clients_to_disconnect`.
            *   If false: Try sending a ping message `await send_json(client_data["websocket"], {"type": "ping"})`. Catch potential `ConnectionClosed` errors during the send (client might have disconnected between the check and the send) and add them to `clients_to_disconnect` if an error occurs.
        *   After iterating, loop through `clients_to_disconnect`:
            *   Call `await ws.close()` for each websocket.
            *   Call `unregister(client_id)` (or let the `finally` block in `connection_handler` handle the unregistration triggered by `ws.close()`). *Important: Ensure `unregister` is robust enough to be called potentially multiple times or when the client is already partially removed.*
6.  **Update `unregister(client_id)`:**
    *   Check if the disconnecting `client_id` exists in `clients`. If not, return early.
    *   Retrieve the `client_data`.
    *   Check if `client_data.get("peer_id")` exists (i.e., the client was paired).
    *   If paired:
        *   Get the `peer_id = client_data["peer_id"]`.
        *   Check if the `peer_id` still exists in the `clients` dictionary.
        *   If the peer exists:
            *   Get the `peer_data = clients[peer_id]`.
            *   Send a notification to the peer: `await send_json(peer_data["websocket"], {"type": "peer_disconnected"})`. Log this action.
            *   Clear the peer's pairing info: `peer_data["peer_id"] = None`.
            *   Remove the entry from the `pairings` dictionary (find the key-value pair involving `client_id` and `peer_id` and delete it).
        *   Log that the peer was notified (or that the peer was not found).
    *   Proceed with the original `unregister` logic (remove `client_id` from `clients`, potentially remove from `pairings` if not done already, log the disconnection).
7.  **Update `main`:**
    *   Before starting the server, create the `periodic_pinger` task: `ping_task = asyncio.create_task(periodic_pinger())`.
    *   In the `finally` block of the server's main execution, ensure the task is cancelled: `ping_task.cancel()`, potentially `await ping_task` with exception handling.

**Client (`client.py`)**

1.  **Update `user_input_handler`:**
    *   Inside the `while True:` loop where input `cmd` is received:
    *   Check if `data_channel` is not `None` AND `data_channel.readyState == "open"`.
        *   If true: Send the message `data_channel.send(cmd)`.
        *   If false (but `peer_id` exists): Print a status like `Cannot send message: Data channel not open.`
        *   If false (and `peer_id` is `None`): Treat input as a pairing request (as in Stage 2).
2.  **Update `setup_datachannel_handlers`:**
    *   Modify the `@data_channel.on("message")` handler:
        *   Print the received message clearly, e.g., `print(f"\n< Peer: {message}")`.
        *   Reprint the input prompt to avoid it being overwritten: `print("> ", end="", flush=True)`.
3.  **Update `handle_server_message`:**
    *   Add a case for `message["type"] == "ping"`:
        *   Call `await send_ws_message({"type": "pong"})`.
    *   Add a case for `message["type"] == "peer_disconnected"`:
        *   Print a notification: `print(f"\n*** Peer disconnected. ***")`.
        *   Set `peer_id = None`.
        *   Close the existing peer connection if it exists and isn't already closed: `if pc and pc.connectionState != "closed": await pc.close()`.
        *   Set `data_channel = None`.
        *   **Crucially:** Re-initialize the `RTCPeerConnection`: `pc = RTCPeerConnection(configuration={'iceServers': [{'urls': STUN_SERVER}]})`.
        *   Re-attach basic event handlers (loggers) to the *new* `pc` instance: `@pc.on(...)`. This includes `icecandidate`, `datachannel`, `iceconnectionstatechange`, `connectionstatechange`. *Ensure these handlers reference the new `pc`.*
        *   Print a readiness message: `print("Ready for new connection.")`.
        *   Reprint the input prompt: `print("> ", end="", flush=True)`.
4.  **Refine Cleanup (`main`'s `finally` block):**
    *   Ensure `pc.close()` is awaited if `pc` exists.
    *   Ensure `websocket.close()` is awaited if `websocket` exists.
    *   Handle potential exceptions during cleanup.

---

### Scope Definition for Stage 5

*   **Essential (In Scope):**
    *   Text message exchange via the WebRTC Data Channel.
    *   Server-side ping/pong mechanism for connection liveness.
    *   Server-side timeout and disconnection of unresponsive clients.
    *   Server notifying the remaining peer about a disconnection.
    *   Client handling the peer disconnection notice: closing the old `RTCPeerConnection`, resetting state (`peer_id`, `data_channel`), and creating a *new* `RTCPeerConnection` instance to be ready for subsequent pairings.
    *   Basic command-line prompt re-display after receiving a peer message.

*   **Out-of-Scope (Previously "Going Above and Beyond"):**
    *   More sophisticated command-line interface (e.g., using `prompt_toolkit`).
    *   Detailed client-side status messages (e.g., "Data channel connecting...", "Data channel closed.").
    *   Adding timestamps to chat messages.
    *   Configuration of ping/timeout values via files or arguments.
    *   More robust error handling for edge cases during cleanup (`pc.close()`, `websocket.close()`).
    *   Explicitly closing the data channel separately before `pc.close()`.
    *   Advanced logging on the server or client.

*   **Extremely Out-of-Scope (Previously "Out-of-Scope"):**
    *   Multi-peer connections or chat rooms.
    *   Video/Audio streaming.
    *   File transfer.
    *   Graphical User Interface (GUI).
    *   Use of TURN servers for improved NAT traversal.
    *   User authentication, accounts, or secure API keys.
    *   Server state persistence across restarts.
    *   Advanced error handling for malformed messages or complex network conditions.
    *   High scalability considerations (design is for few simultaneous users).
    *   Automatic client reconnection to the *server* if the WebSocket connection drops.
    *   Re-establishing signaling for an existing WebRTC connection if only the WebSocket drops.
