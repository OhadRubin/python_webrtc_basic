# test_strict_e2e_stage2.py
import pexpect
import unittest
import sys
import time
import re
import logging
import os
import signal

# --- Configuration ---
SERVER_CMD = f"{sys.executable} server.py"
CLIENT_CMD = f"{sys.executable} client.py"
SERVER_READY_PATTERN = r"Server listening on ws://.*:8765"  # Regex pattern
CLIENT_ID_PATTERN = r"\*\*\* Your Client ID: ([0-9a-f-]+) \*\*\*"  # Regex pattern with capture group
CLIENT_CONNECTED_PATTERN = r"Connected to server\."  # Add pattern for successful connection
CLIENT_PROMPT_PATTERN = r">"  # Add pattern for the prompt
CLIENT_PAIRED_INITIATOR_PATTERN = r"\*\*\* Paired with ([0-9a-f-]+)! You are the initiator\. \*\*\*"
CLIENT_PAIRED_RECEIVER_PATTERN = r"\*\*\* Paired with ([0-9a-f-]+)! You are the receiver\. \*\*\*"
CLIENT_ERROR_PATTERN = r"\*\*\* Server Error: (.*) \*\*\*"
CLIENT_PROMPT = "> "  # Expected prompt after connection/pairing (adjust if client.py changes)
CLIENT_EXCEPTION_PATTERN = r"Traceback \(most recent call last\)"  # Generic traceback indicator

# Shorter timeout for expected immediate responses, longer for potential waits
EXPECT_TIMEOUT_SHORT = 3
EXPECT_TIMEOUT_LONG = 5  # Increasing timeout for client operations
SETUP_TIMEOUT = 5  # Increase timeout for server/client startup

# --- Logging ---
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s: [TestStrict] %(message)s"
)
test_logger = logging.getLogger(__name__)


class TestStrictE2EStage2(unittest.TestCase):

    server_process = None
    client_processes = {}  # Dictionary to store name: {proc: process, id: client_id}

    @classmethod
    def setUpClass(cls):
        """Starts the server once before all tests in the class."""
        test_logger.info("Starting server process...")
        # Log server output directly to test output for debugging
        cls.server_process = pexpect.spawn(
            SERVER_CMD, encoding="utf-8", timeout=SETUP_TIMEOUT
        )  # codec_errors='replace'
        cls.server_process.logfile_read = sys.stdout  # Show server logs during test run

        try:
            cls.server_process.expect(SERVER_READY_PATTERN, timeout=SETUP_TIMEOUT)
            test_logger.info("Server process reported ready.")
            # Give it more time to fully bind
            time.sleep(3)
        except (pexpect.TIMEOUT, pexpect.EOF) as e:
            test_logger.error(f"Server failed to start within timeout: {e}")
            cls.server_process.terminate(force=True)
            raise AssertionError(f"Server failed to start: {e}") from e

    @classmethod
    def tearDownClass(cls):
        """Stops the server once after all tests."""
        if cls.server_process and cls.server_process.isalive():
            test_logger.info("Stopping server process...")
            # Send SIGTERM first for potentially cleaner shutdown
            try:
                os.kill(cls.server_process.pid, signal.SIGTERM)
                cls.server_process.wait()  # Wait for graceful exit
                test_logger.info("Server process terminated gracefully.")
            except ProcessLookupError:
                test_logger.warning("Server process already exited.")
            except Exception:  # Fallback if wait fails or other error
                if cls.server_process.isalive():
                    cls.server_process.terminate(force=True)
                    test_logger.warning("Server process terminated forcefully.")
        else:
            test_logger.info("Server process was not running or already stopped.")

    def tearDown(self):
        """Stops all client processes after each test."""
        test_logger.info("--- Tearing down test ---")
        for name, client_info in self.client_processes.items():
            proc = client_info.get("proc")
            if proc and proc.isalive():
                test_logger.info(f"Stopping client process: {name}")
                proc.terminate(
                    force=True
                )  # Clients often don't have graceful shutdown signal handling
        self.client_processes.clear()
        time.sleep(0.2)  # Allow OS to release resources
    def _start_client(self, name):
        """Helper to start a client process and extract its ID."""
        test_logger.info(f"Starting client process: {name} with command: {CLIENT_CMD}")
        proc = pexpect.spawn(CLIENT_CMD, encoding="utf-8", timeout=EXPECT_TIMEOUT_LONG)
        proc.logfile_read = sys.stdout  # Show client logs
        self.client_processes[name] = {
            "proc": proc,
            "id": None,
        }  # Store proc immediately

        try:
            # Look for successful connection indicators
            test_logger.info(f"Waiting for {name} to connect to server and receive ID...")
            
            # Wait for the client ID pattern directly
            match_index = proc.expect([
                CLIENT_ID_PATTERN,     # 0: Successfully got ID
                pexpect.EOF,           # 1: EOF
                pexpect.TIMEOUT,       # 2: Timeout (longer timeout here)
            ], timeout=EXPECT_TIMEOUT_LONG)
            
            if match_index == 0:  # Got the client ID
                client_id = proc.match.group(1).strip()
                self.assertIsNotNone(client_id, f"{name} ID extraction failed.")
                self.client_processes[name]["id"] = client_id
                test_logger.info(f"Client {name} started with ID: {client_id}")
                
                # Also wait for the prompt to appear after the ID
                test_logger.info(f"Waiting for {name} prompt...")
                prompt_index = proc.expect([CLIENT_PROMPT_PATTERN, pexpect.TIMEOUT], timeout=EXPECT_TIMEOUT_SHORT)
                if prompt_index == 0:
                    test_logger.info(f"Client {name} prompt ready.")
                return proc, client_id
            else:
                output_before_fail = proc.before or ""
                error_reason = "EOF" if match_index == 1 else "timeout"
                test_logger.error(f"{name} failed to receive ID. Match index: {match_index}. Reason: {error_reason}. Output: '{output_before_fail}'")
                raise AssertionError(f"Client {name} failed to receive ID. Output: {output_before_fail[-500:]}")

        except (pexpect.TIMEOUT, pexpect.EOF, Exception) as e:
            test_logger.error(f"Failed to start or get ID for client {name}: {e}")
            proc.terminate(force=True)
            raise AssertionError(f"Client {name} setup failed: {e}") from e

    def _send_command(self, proc, name, command):
        """Sends a command (like a peer ID) to a client process."""
        test_logger.info(f"Sending command '{command}' to {name}")
        # Make sure we have a prompt
        index = proc.expect([CLIENT_PROMPT_PATTERN, pexpect.TIMEOUT, CLIENT_EXCEPTION_PATTERN], timeout=EXPECT_TIMEOUT_SHORT)
        if index == 2:
            output = proc.before + (proc.after or "")
            raise AssertionError(f"{name} had an unexpected exception before command: {output[-500:]}")
        elif index != 0:
            test_logger.warning(f"No prompt found for {name} before sending command, proceeding anyway.")
        
        proc.sendline(command)
        # Give a small delay to ensure command processing
        time.sleep(0.5)
        
        # Check for exceptions immediately after sending
        try:
            exc_check = proc.expect([CLIENT_EXCEPTION_PATTERN, pexpect.TIMEOUT], timeout=1)
            if exc_check == 0:
                output = proc.before + (proc.after or "")
                raise AssertionError(f"{name} had an unexpected exception after sending command: {output[-500:]}")
        except pexpect.TIMEOUT:
            # Timeout is expected here - it means no exception was found
            pass

    def _expect_paired(self, proc, name, expected_peer_id, is_initiator):
        """Expects the correct 'paired' message."""
        pattern = (
            CLIENT_PAIRED_INITIATOR_PATTERN
            if is_initiator
            else CLIENT_PAIRED_RECEIVER_PATTERN
        )
        role = "initiator" if is_initiator else "receiver"
        test_logger.info(
            f"Expecting {name} to receive paired confirmation ({role}) with {expected_peer_id}"
        )
        try:
            match_index = proc.expect(
                [pattern, pexpect.TIMEOUT, pexpect.EOF, CLIENT_EXCEPTION_PATTERN], timeout=EXPECT_TIMEOUT_LONG
            )
            if match_index == 0:
                matched_peer_id = proc.match.group(1).strip()
                self.assertEqual(
                    matched_peer_id,
                    expected_peer_id,
                    f"{name} paired with wrong peer ID.",
                )
                test_logger.info(f"{name} received correct paired confirmation.")
                
                # Also expect the prompt to reappear
                prompt_index = proc.expect([CLIENT_PROMPT_PATTERN, pexpect.TIMEOUT, CLIENT_EXCEPTION_PATTERN], timeout=EXPECT_TIMEOUT_SHORT)
                if prompt_index == 0:
                    test_logger.info(f"Client {name} prompt ready after pairing.")
                elif prompt_index == 2:
                    output = proc.before + (proc.after or "")
                    raise AssertionError(f"{name} had an unexpected exception after pairing: {output[-500:]}")
            elif match_index == 3:  # Exception detected!
                # Capture more context from the output to show the exception
                output = proc.before + (proc.after or "")
                raise AssertionError(f"{name} had an unexpected exception: {output[-500:]}")
            else:
                # Handle timeout or EOF
                if match_index == 1:
                    error_type = "timeout"
                else:  # match_index == 2
                    error_type = "EOF"
                raise AssertionError(
                    f"{name} did not receive expected paired message. Index: {match_index} ({error_type})"
                )
        except (pexpect.TIMEOUT, pexpect.EOF, Exception) as e:
            raise AssertionError(
                f"Error expecting paired message for {name}: {e}"
            ) from e

    def _expect_error(self, proc, name, expected_error_substring):
        """Expects a specific server error message."""
        test_logger.info(
            f"Expecting {name} to receive error containing '{expected_error_substring}'"
        )
        try:
            match_index = proc.expect(
                [CLIENT_ERROR_PATTERN, pexpect.TIMEOUT, pexpect.EOF, CLIENT_EXCEPTION_PATTERN],
                timeout=EXPECT_TIMEOUT_LONG,
            )
            if match_index == 0:
                actual_error = proc.match.group(1).strip()
                self.assertIn(
                    expected_error_substring,
                    actual_error,
                    f"{name} received wrong error message: {actual_error}",
                )
                test_logger.info(f"{name} received expected error message.")
                
                # Also expect the prompt to reappear
                prompt_index = proc.expect([CLIENT_PROMPT_PATTERN, pexpect.TIMEOUT, CLIENT_EXCEPTION_PATTERN], timeout=EXPECT_TIMEOUT_SHORT)
                if prompt_index == 0:
                    test_logger.info(f"Client {name} prompt ready after error.")
                elif prompt_index == 2:
                    output = proc.before + (proc.after or "")
                    raise AssertionError(f"{name} had an unexpected exception after error: {output[-500:]}")
            elif match_index == 3:  # Exception detected!
                output = proc.before + (proc.after or "")
                raise AssertionError(f"{name} had an unexpected exception: {output[-500:]}")
            else:
                # Handle timeout or EOF
                if match_index == 1:
                    error_type = "timeout"
                else:  # match_index == 2
                    error_type = "EOF"
                raise AssertionError(
                    f"{name} did not receive expected error message. Index: {match_index} ({error_type})"
                )
        except (pexpect.TIMEOUT, pexpect.EOF, Exception) as e:
            raise AssertionError(
                f"Error expecting error message for {name}: {e}"
            ) from e

    # --- Test Cases ---

    def test_successful_pairing(self):
        """Tests two clients connecting and successfully pairing via user simulation."""
        proc_a, id_a = self._start_client("Client A")
        proc_b, id_b = self._start_client("Client B")

        # Client A enters Client B's ID
        self._send_command(proc_a, "Client A", id_b)

        # Verify confirmations
        self._expect_paired(proc_a, "Client A", id_b, is_initiator=True)
        self._expect_paired(proc_b, "Client B", id_a, is_initiator=False)

    # def test_pairing_errors(self):
    #     """Tests various pairing failure scenarios via user simulation."""
    #     proc_a, id_a = self._start_client("Client A")
    #     proc_b, id_b = self._start_client("Client B")
    #     proc_c, id_c = self._start_client("Client C")

    #     # 1. Target Not Found
    #     fake_id = "non-existent-client-id"
    #     self._send_command(proc_a, "Client A", fake_id)
    #     self._expect_error(proc_a, "Client A", "Target client not found")

    #     # 2. Setup for Already Paired errors: Pair A and B successfully
    #     self._send_command(proc_a, "Client A", id_b)
    #     self._expect_paired(proc_a, "Client A", id_b, is_initiator=True)
    #     self._expect_paired(proc_b, "Client B", id_a, is_initiator=False)
    #     test_logger.info("Setup complete for already-paired tests.")

    #     # 3. Requester Already Paired
    #     self._send_command(proc_a, "Client A", id_c)  # A tries to pair with C
    #     self._expect_error(proc_a, "Client A", "You are already paired")

    #     # 4. Target Already Paired
    #     self._send_command(proc_c, "Client C", id_b)  # C tries to pair with B
    #     self._expect_error(proc_c, "Client C", "Target client is already paired")

    # def test_paired_client_disconnect_cleanup_strict(self):
    #     """Tests server cleanup when a paired client disconnects (Strict E2E)."""
    #     proc_a, id_a = self._start_client("Client A")
    #     proc_b, id_b = self._start_client("Client B")

    #     # Pair A and B successfully first
    #     self._send_command(proc_a, "Client A", id_b)
    #     self._expect_paired(proc_a, "Client A", id_b, is_initiator=True)
    #     self._expect_paired(proc_b, "Client B", id_a, is_initiator=False)
    #     test_logger.info("Setup complete - A and B are paired.")

    #     # Terminate Client A's process
    #     test_logger.info(f"Terminating Client A ({id_a})...")
    #     proc_a.terminate(force=True)
    #     time.sleep(1)  # Allow server time to process disconnect

    #     # Verify Client B did NOT receive any notification
    #     # We check this implicitly by ensuring the next pairing attempt fails as expected
    #     test_logger.info(
    #         "Verifying Client B received no peer disconnect notification (implicitly)..."
    #     )

    #     # Start Client C
    #     proc_c, id_c = self._start_client("Client C")

    #     # Attempt to pair Client B with Client C
    #     self._send_command(proc_b, "Client B", id_c)

    #     # Expect B to fail because the server still thinks B is paired (Stage 2)
    #     self._expect_error(proc_b, "Client B", "You are already paired")
    #     test_logger.info(
    #         "Verified Client B is still considered paired by the server after A disconnected."
    #     )


if __name__ == "__main__":
    unittest.main()
