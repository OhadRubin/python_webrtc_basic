# Stage 1 - Basic Server Connection and Client ID Assignment
# 
**Goal:** Verify the server can start, clients can connect via WebSocket, and each client receives a unique ID from the server. Test basic disconnect handling on the server.

**Scope:**

*   **Essential (In Scope for Stage 1):**
    *   Server: Basic WebSocket listener setup.
    *   Server: Management of connected clients in memory (simple dictionary).
    *   Server: Generation of unique IDs for new clients.
    *   Server: Sending the unique ID (`"your_id"` message) to the connecting client.
    *   Server: Detecting client disconnection.
    *   Server: Cleaning up server state upon client disconnection (removing from dictionary).
    *   Server: Basic logging for connections/disconnections.
    *   Client: Basic WebSocket connection logic.
    *   Client: Receiving and processing the `"your_id"` message from the server.
    *   Client: Displaying the received ID.
    *   Client: Basic logging for connection status.
    *   Client: Handling connection closure/errors gracefully.
*   **Out-of-Scope (Functionality deferred to later stages, previously "Going Above and Beyond"):**
    *   Sophisticated state management beyond a simple client dictionary.
    *   Storing additional client metadata (IP, connection time, etc.).
    *   Server broadcasting messages to multiple clients.
    *   Client sending *any* messages to the server.
    *   Detailed error reporting beyond basic connection/parsing errors.
    *   Client-side reconnection logic.
    *   Advanced async task management (e.g., `asyncio.gather`, task cancellation beyond server shutdown).
    *   Using configuration files (constants are sufficient).
*   **Extremely Out-of-Scope (Functionality not part of Stage 1, previously "Out-of-Scope"):**
    *   Any pairing logic (server-side `pairings` dictionary, `handle_pair_request`).
    *   Client sending pairing requests or handling user input for pairing.
    *   Any WebRTC components (`aiortc`, `RTCPeerConnection`, SDP Offer/Answer, ICE Candidates).
    *   Data channel setup or communication.
    *   Server-side Ping/Pong mechanism for keepalives.
    *   Notifying a *peer* client about disconnection.
    *   API key generation or usage for client identification/connection.
    *   Message relaying between clients via the server.

---

**Implementation Plan (Stage 1 Essentials Only):**

**1. Server Implementation (`server.py`)**

*   **Dependencies:** `websockets`, `asyncio`, `logging`, `json`, `uuid`
*   **Configuration:**
    *   Define constants: `SERVER_HOST = "localhost"`, `SERVER_PORT = 8765`.
*   **Logging:**
    *   Set up basic logging (e.g., `logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')`).
*   **State:**
    *   Initialize `clients = {}` (dictionary to store `client_id: websocket_connection`).
*   **Helper Functions:**
    *   `send_json(ws, data)`:
        *   Takes a WebSocket connection (`ws`) and a Python dictionary (`data`).
        *   Uses `json.dumps` to serialize the dictionary.
        *   Uses `await ws.send()` to send the JSON string.
        *   Includes basic error handling (e.g., log if send fails, although connection closure might be handled elsewhere).
*   **Core Logic:**
    *   `register(ws)`:
        *   Generates a unique client ID: `client_id = str(uuid.uuid4())`.
        *   Stores the client: `clients[client_id] = ws`.
        *   Logs the connection: `logging.info(f"Client {client_id} connected from {ws.remote_address}")`.
        *   Sends the ID to the client: `await send_json(ws, {"type": "your_id", "id": client_id})`.
        *   Returns the `client_id`.
    *   `unregister(client_id)`:
        *   Checks if `client_id` exists in `clients`.
        *   If yes, removes the client: `del clients[client_id]`.
        *   Logs the disconnection: `logging.info(f"Client {client_id} disconnected.")`.
        *   If no (shouldn't happen with proper flow but good practice), logs a warning.
    *   `connection_handler(ws, path)`:
        *   Calls `client_id = await register(ws)`.
        *   Enters a `try...finally` block:
            *   **`try`:** Enters a basic message receiving loop (`async for message in ws:`). For Stage 1, this loop can be empty or just log received messages, as the client isn't expected to send anything meaningful yet. Handle potential `websockets.exceptions.ConnectionClosedOK`, `ConnectionClosedError`.
            *   **`finally`:** Calls `unregister(client_id)` to ensure cleanup regardless of how the connection ends.
*   **Main Execution:**
    *   `main()`:
        *   Logs "Server starting...".
        *   Starts the server: `server = await websockets.serve(connection_handler, SERVER_HOST, SERVER_PORT)`.
        *   Logs "Server listening on ws://{SERVER_HOST}:{SERVER_PORT}".
        *   Keeps the server running indefinitely: `await server.wait_closed()` (or an equivalent like `asyncio.Future()`).
    *   `if __name__ == "__main__":`:
        *   Runs the `main` function using `asyncio.run(main())`.

**2. Client Implementation (`client.py`)**

*   **Dependencies:** `websockets`, `asyncio`, `logging`, `json`
*   **Configuration:**
    *   Define constant: `SERVER_URL = "ws://localhost:8765"`.
*   **Logging:**
    *   Set up basic logging similar to the server.
*   **State:**
    *   Initialize globals: `websocket = None`, `my_id = None`.
*   **Core Logic:**
    *   `handle_server_message(message)`:
        *   Takes a raw message string from the WebSocket.
        *   Uses `json.loads` to parse the message inside a `try...except json.JSONDecodeError` block. Log errors.
        *   Checks `data.get("type")`.
        *   If `type == "your_id"`:
            *   Stores the ID: `global my_id; my_id = data.get("id")`.
            *   Prints the ID clearly: `print(f"*** Your Client ID: {my_id} ***")` or logs it.
        *   For any other message type in Stage 1, just log it as unhandled: `logging.warning(f"Unhandled message type: {data.get('type')}")`.
*   **Main Execution:**
    *   `main()`:
        *   Logs "Connecting to server at {SERVER_URL}...".
        *   Enters a `try...except...finally` block for connection management:
            *   **`try`:**
                *   Connects to the server: `async with websockets.connect(SERVER_URL) as ws:`.
                *   Assigns to global: `global websocket; websocket = ws`.
                *   Logs "Connected to server.".
                *   Enters the listener loop: `async for message in websocket:`.
                *   Calls `await handle_server_message(message)` for each received message.
            *   **`except websockets.exceptions.ConnectionClosedError as e:`:**
                *   Logs "Connection closed unexpectedly: {e}".
            *   **`except Exception as e:`:** (Catch broader errors like refused connection)
                *   Logs "Failed to connect or error during communication: {e}".
            *   **`finally`:**
                *   Logs "Disconnecting...".
                *   Sets `websocket = None` (optional, good practice).
                *   Logs "Client shut down.".
    *   `if __name__ == "__main__":`:
        *   Runs the `main` function using `asyncio.run(main())`.

This detailed plan provides the essential building blocks for Stage 1, ensuring that the core goal of server connection and ID assignment can be implemented and tested before moving on to more complex features like pairing and WebRTC.