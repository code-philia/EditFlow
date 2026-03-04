import os
import re
import json
import time
import threading
import functools
import subprocess
from abc import ABC, abstractmethod
from torch.utils.data import DataLoader
from typing import List, Dict, Optional

def timeout_decorator(timeout, timeout_return=None):
    """
    Decorator to add a timeout to any function.
    Returns `timeout_return` when the function exceeds the timeout.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            result_container = {}
            exception_container = {}

            def target():
                try:
                    result_container['result'] = func(*args, **kwargs)
                except Exception as e:
                    exception_container['exception'] = e

            thread = threading.Thread(target=target)
            thread.daemon = True  # Set the thread as a daemon thread
            thread.start()
            thread.join(timeout)

            if thread.is_alive():
                raise TimeoutError(f"Function '{func.__name__}' exceeded timeout of {timeout} seconds.")

            if 'exception' in exception_container:
                raise exception_container['exception']

            return result_container.get('result')
        return wrapper
    return decorator

class LanguageServer(ABC):
    def __init__(self, language_id: str, server_command: List[str], log: bool = False):
        """
        Initialize the language server process.
        """
        self.language_id = language_id
        try:
            self.process = subprocess.Popen(
                server_command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=0
            )
        except Exception as e:
            print(f"Failed to start language server process: {e}")
            raise
        self.request_id: int = 1
        self.log: bool = log
        self.messages: List[Dict] = []
        self.workspace_file_version: Dict[str, int] = {}

    def initialize(self, workspace_folders: list[str] | str, wait_time: float = 0.5):
        if isinstance(workspace_folders, str):
            workspace_folders = [workspace_folders]
        request_id = self._send_request(
            "initialize",
            params={
                "processId": None,
                "workspaceFolders": [
                    {
                        "uri": f"file://{workspace_folder}",
                        "name": f"Workspace {i}"
                    } for i, workspace_folder in enumerate(workspace_folders)
                ],
                "capabilities": self._get_capabilities()
            }
        )
        self._get_messages(request_id=request_id, message_num=1, wait_time=wait_time)
        self._send_notification("initialized")

    def _get_capabilities(self) -> Dict:
        """
        Get the capabilities for the language server.
        Should be overridden by subclasses if needed.
        """
        return {
            "textDocument": {
                "references": {"dynamicRegistration": True},
                "codeAction": {
                    "codeActionLiteralSupport": {
                        "codeActionKind": {
                            "valueSet": ["", "quickfix", "refactor", "refactor.extract", "refactor.inline",
                                       "refactor.rewrite", "source", "source.organizeImports"]
                        }
                    }
                }
            },
            "diagnostics": {
                "dynamicRegistration": True
            }
        }

    def did_open(self, file_path):
        with open(file_path, 'r') as f:
            file_content = f.read()

        self._send_notification(
            "textDocument/didOpen",
            params={
                "textDocument": {
                    "uri": f"file://{file_path}",
                    "languageId": self.language_id,
                    "version": 1,
                    "text": file_content
                }
            }
        )
        self.workspace_file_version[file_path] = 1
    
    def did_change(self, file_path: str):
        # 读取整个文件内容
        with open(file_path, 'r') as f:
            content = f.read()
        
        file_version = self.workspace_file_version.get(file_path, 0)
        self._send_notification(
            "textDocument/didChange",
            params={
                "textDocument": {
                    "uri": f"file://{file_path}",
                    "version": file_version + 1
                },
                "contentChanges": [
                    {
                        "text": content
                    }
                ]
            }
        )
        self.workspace_file_version[file_path] = file_version + 1
    
    def open_in_batch(self, file_paths: List[str]):
        for file_path in file_paths:
            try:
                self.did_open(file_path)
            except Exception as e:
                continue
            
    def rename(self, file_path: str, position: dict[str, int], new_name: str, wait_time: float = 0.5):
        if self.workspace_file_version.get(file_path, 0) == 0:
            self.did_open(file_path)
        else:
            self.did_change(file_path)
        
        request_id = self._send_request(
            "textDocument/rename",
            params={
                "textDocument": {
                    "uri": f"file://{file_path}"
                },
                "position": position,
                "newName": new_name
            }
        )
        messages = self._get_messages(request_id=request_id, message_num=1, wait_time=wait_time)
        return messages
    
    def references(self, file_path, position, wait_time: float = 0.5, include_declaration: bool = True):
        if self.workspace_file_version.get(file_path, 0) == 0:
            self.did_open(file_path)
        else:
            self.did_change(file_path)
        
        request_id = self._send_request(
            "textDocument/references",
            params={
                "textDocument": {
                    "uri": f"file://{file_path}"
                },
                "position": position,
                "context": {
                    "includeDeclaration": include_declaration
                }
            }
        )
        messages = self._get_messages(request_id=request_id, message_num=1, wait_time=wait_time)
        return messages
    
    def definitions(self, file_path, position, wait_time: float = 0.5):
        if self.workspace_file_version.get(file_path, 0) == 0:
            self.did_open(file_path)
        else:
            self.did_change(file_path)
            
        request_id = self._send_request(
            "textDocument/definition",
            params={
                "textDocument": {
                    "uri": f"file://{file_path}"
                },
                "position": position
            }
        )
        messages = self._get_messages(request_id=request_id, message_num=1, wait_time=wait_time)
        return messages
    
    def diagnostics(self, file_path, wait_time: float = 0.5):
        if self.workspace_file_version.get(file_path, 0) == 0:
            self.did_open(file_path)
        else:
            self.did_change(file_path)
        
        messages = self._get_messages(expect_method="textDocument/publishDiagnostics", message_num=1, wait_time=wait_time)
        return messages

    def close(self):
        request_id = self._send_request("shutdown")
        self._get_messages(request_id=request_id, message_num=1, wait_time=0.5)
        self._send_notification("exit")
        self.process.terminate()
        self.process.wait()
        print("Server closed")

    def get_all_file_paths(self, workspace_path: str) -> List[str]:
        file_paths = []
        for root, _, files in os.walk(workspace_path):
            for file in files:
                file_paths.append(os.path.join(root, file))
        return file_paths

    def _read_by_brace_matching(self, timeout: float = 0.1) -> Optional[str]:
        """
        Read a complete JSON message by matching the braces.
        
        Args:
            timeout: Timeout for select (seconds)
            
        Returns:
            Optional[str]: Return a complete JSON message string, or None if timeout
        """
        buffer = ""
        brace_count = 0
        inside_str = False
        escaped = False  # 处理转义字符
        
        while True:
            char = self.process.stdout.read(1)
            
            if buffer == "":
                assert char == "{"
                
            buffer += char
            
            if escaped:
                escaped = False
                continue
                
            if char == '\\':
                escaped = True
            elif char == '"':
                inside_str = not inside_str
            elif not inside_str:
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    
            if brace_count == 0:
                return buffer
        
    @timeout_decorator(timeout=5, timeout_return=None)
    def _read_lsp_messages(self, request_id: Optional[int] = None, expect_method: Optional[str] = None, message_num: Optional[int] = None, wait_time: Optional[float] = None):
        """
        Continuously read and parse JSON-RPC messages from the server's stdout.
        Messages are stored in the self.messages list.
        By specifying the `request_id` or `expect_method`, the function will stop when the message is received.
        If both parameters are set, the function will stop when either condition is met.
        """
        buffer = ""
        start_time = time.time()
        while True:
            line = self.process.stdout.readline()
            if not line:  # Exit if no more output is available
                break
            buffer += line
            match = re.search(r"Content-Length: (\d+)", buffer)
            if match:
                self.process.stdout.readline()  # Skip the blank line
                message = self._read_by_brace_matching()
                try:
                    json_message = json.loads(message.strip())
                    if self._is_desired_message(json_message, request_id, expect_method):
                        return None
                except json.JSONDecodeError as e:
                    raise Exception(f"JSON Parse Error: {e}, Original Message: {message}")
                buffer = ""  # Reset buffer after processing a message
            
            if wait_time is not None and (time.time() - start_time) >= wait_time:
                return None
            if message_num is not None and len(self.messages) >= message_num:
                return None 
    
    def _is_desired_message(self, json_message: Dict, request_id: Optional[int] = None, expect_method: Optional[str] = None) -> bool:
        if request_id is not None: # if request_id is specified, only add the message if it has the same request_id
            if "id" in json_message: # if the response is a request response
                if json_message["id"] == request_id:
                    self.messages.append(json_message)
                    if self.log:
                        print(f"[RECEIVED] {json.dumps(json_message, indent=2, ensure_ascii=False)}")
                    return True
                else:
                    return False
        elif expect_method is not None: # if expect_method is specified, only add the message if it has the same method
            if "method" in json_message and json_message["method"] == expect_method:
                self.messages.append(json_message)
                if self.log:
                    print(f"[RECEIVED] {json.dumps(json_message, indent=2, ensure_ascii=False)}")
                return True
            else:
                return False
        else: # if request_id is not specified, add all messages
            self.messages.append(json_message)
            return True
        
    def _get_messages(self, request_id: Optional[int] = None, expect_method: Optional[str] = None, message_num: Optional[int] = None, wait_time: Optional[float] = None) -> List[Dict]:
        """
        Retrieve messages from the server based on specified conditions:
        - request_id: Stop when a specific request ID is received.
        - expect_method: Stop when a specific method is received.
        - message_num: Stop when a specific number of messages are received.
        - wait_time: Stop after the specified amount of time (in seconds).
        If both parameters are set, the function will stop when either condition is met.

        Args:
            request_id (Optional[int]): Request ID of the message to retrieve.
            expect_method (Optional[str]): Method of the message to retrieve.
            message_num (Optional[int]): Number of messages to retrieve.
            wait_time (Optional[float]): Time in seconds allowed to wait for messages.

        Returns:
            List[Dict]: A list of received JSON-RPC messages.
        """
        self._read_lsp_messages(request_id=request_id, expect_method=expect_method, message_num=message_num, 
        wait_time=wait_time)  # Read all current messages
        messages, self.messages = self.messages, []  # Return and clear message list
        return messages
    
    def _send_to_process(self, message: str):
        if self.process.poll() is not None:
            stderr_output = self.process.stderr.read()
        if os.name == "nt": # Windows
            # TODO: Just a speculation, not verified.
            self.process.stdin.write(f"Content-Length: {len(message)}\n\n{message}")
        elif os.name == "posix": # Linux, macOS
            self.process.stdin.write(f"Content-Length: {len(message)}\r\n\r\n{message}")
        self.process.stdin.flush()
        
    def _create_message(self, method: str, params: dict = None, is_request: bool = True) -> str:
        message_data = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if is_request:
            message_data["id"] = self.request_id
            self.request_id += 1
        if params:
            message_data["params"] = params

        return message_data

    def _send_notification(self, method: str, params: dict = None):
        notification = self._create_message(method, params, is_request=False)
        notification = json.dumps(notification)
        self._send_to_process(notification)

    def _send_request(self, method: str, params: dict = None):
        request = self._create_message(method, params, is_request=True)
        request_id = request["id"]
        request_json = json.dumps(request)
        self._send_to_process(request_json)
        return request_id
    
    @abstractmethod
    def _parse_rename_response(self, response, edits):
        """
        Parse the response of rename request and update the edits
        Implemented in subclasses
        """
        pass
    
    @abstractmethod
    def _filter_diagnostics(self, diagnostics, last_edit_at_range, init_diagnose_msg):
        """
        Filter out the diagnostics that are not very helpful
        If not implemented, return the original diagnostics
        """
        pass
