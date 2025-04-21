# WebRTC Signaling Server and Client

This project implements a WebRTC signaling server and client for establishing peer-to-peer connections.

## Features

- WebSocket-based signaling server
- Client implementation with WebRTC data channel support
- Connection pairing via unique IDs
- ICE candidate exchange
- Keepalive with ping/pong messages
- Automatic peer disconnection detection

## Requirements

- Python 3.7+
- Required packages:
  - websockets
  - aiortc
  - asyncio

## Installation

1. Clone this repository
2. Install dependencies:

```bash
pip install websockets aiortc asyncio
```

## Usage

### Starting the Server

```bash
python server.py
```

The server will start on port 8765 by default.

### Starting a Client

```bash
python client.py
```

After starting the client:
1. Note your assigned Client ID
2. Either:
   - Enter another client's ID to initiate a connection
   - Wait for another client to connect to you
3. Once connected, type messages to send them via the WebRTC data channel

## Running Tests

Run the end-to-end tests with:

```bash
python test_e2e.py
```

The test will:
1. Start the server automatically
2. Simulate client connections and pairing
3. Test signaling message exchange
4. Test disconnect notifications

## How It Works

1. Clients connect to the signaling server via WebSockets
2. Each client receives a unique ID
3. One client initiates pairing with another client's ID
4. The server facilitates WebRTC signaling (SDP offers/answers, ICE candidates)
5. Once WebRTC connection is established, communication happens directly between peers
6. The server maintains connections with ping/pong messages and handles disconnection events# python_webrtc_basic
