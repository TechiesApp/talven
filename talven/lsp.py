"""Bounded stdio LSP: sync, diagnostics, navigation, symbols, formatting edits.

Documents are analyzed from editor-supplied text. The server never opens a URI,
executes a compiler subprocess, installs a dependency, or runs source programs.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import BinaryIO

from . import VERSION
from .formatter import format_source
from .frontend import Analysis, CompileError, Span, analyze, source_range

MAX_MESSAGE_BYTES = 1024 * 1024
MAX_DOCUMENTS = 32


def read_message(stream: BinaryIO) -> dict | None:
    size = None
    header_size = 0
    while True:
        line = stream.readline(8193)
        if not line:
            if header_size == 0:
                return None
            raise ValueError("Incomplete LSP header")
        header_size += len(line)
        if header_size > 8192:
            raise ValueError("LSP header exceeds limit")
        if line in (b"\r\n", b"\n"):
            break
        key, value = line.decode("ascii").split(":", 1)
        if key.strip().lower() == "content-length":
            value = value.strip()
            if size is not None or not value.isascii() or not value.isdigit() or len(value) > 8:
                raise ValueError("Invalid Content-Length")
            size = int(value)
    if size is None or not 0 < size <= MAX_MESSAGE_BYTES:
        raise ValueError("Missing or oversized Content-Length")
    body = stream.read(size)
    if len(body) != size:
        raise ValueError("Incomplete LSP message")
    message = json.loads(body)
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        raise ValueError("Expected a JSON-RPC 2.0 object")
    pending = [(message, 1)]
    while pending:
        value, depth = pending.pop()
        if depth > 128:
            raise ValueError("LSP JSON nesting exceeds limit")
        children = value.values() if isinstance(value, dict) else value if isinstance(value, list) else ()
        pending.extend((child, depth + 1) for child in children)
    return message


def write_message(stream: BinaryIO, message: dict):
    body = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    stream.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body)
    stream.flush()


def offset_at(source: str, point: dict) -> int | None:
    if not isinstance(point, dict):
        return None
    line, character = point.get("line"), point.get("character")
    if type(line) is not int or type(character) is not int or line < 0 or character < 0:
        return None
    lines = source.split("\n")
    if line >= len(lines):
        return None
    units = 0
    for index, char in enumerate(lines[line]):
        if units == character:
            return sum(len(s) + 1 for s in lines[:line]) + index
        units += len(char.encode("utf-16-le")) // 2
    if units == character:
        return sum(len(s) + 1 for s in lines[:line]) + len(lines[line])
    return None


@dataclass
class Document:
    source: str
    version: int
    analysis: Analysis | None


class Server:
    def __init__(self, output: BinaryIO):
        self.output = output
        self.documents: dict[str, Document] = {}
        self.initialized = False
        self.shutdown = False

    def send(self, **fields):
        write_message(self.output, {"jsonrpc": "2.0", **fields})

    def update(self, uri: str, version: int, source: str):
        if not isinstance(uri, str) or type(version) is not int or not isinstance(source, str):
            raise ValueError("Invalid document")
        previous = self.documents.get(uri)
        if previous and version <= previous.version:
            return
        if previous is None and len(self.documents) >= MAX_DOCUMENTS:
            raise ValueError("Open-document limit reached")
        try:
            result = analyze(source)
            diagnostics = []
        except CompileError as error:
            result = None
            diagnostics = [error.diagnostic(source)]
        self.documents[uri] = Document(source, version, result)
        self.send(method="textDocument/publishDiagnostics",
                  params={"uri": uri, "version": version, "diagnostics": diagnostics})

    def handle(self, message: dict) -> int | None:
        method, params = message.get("method"), message.get("params", {})
        request = "id" in message
        identity = message.get("id")
        if method == "exit":
            return 0 if self.shutdown else 1
        try:
            if not isinstance(params, dict):
                raise ValueError("Request parameters must be an object")
            if method == "initialize" and not self.initialized:
                self.initialized = True
                self.send(id=identity, result={"capabilities": {
                    "positionEncoding": "utf-16", "textDocumentSync": {"openClose": True, "change": 1},
                    "hoverProvider": True, "definitionProvider": True, "documentSymbolProvider": True,
                    "documentFormattingProvider": True},
                    "serverInfo": {"name": "talven", "version": VERSION}})
                return None
            if not self.initialized:
                if request:
                    self.send(id=identity, error={"code": -32002, "message": "Server not initialized"})
                return None
            if self.shutdown:
                if request:
                    self.send(id=identity, error={"code": -32600, "message": "Server has shut down"})
                return None
            if method == "shutdown":
                self.shutdown = True
                self.send(id=identity, result=None)
                return None
            if method == "textDocument/didOpen":
                doc = params["textDocument"]
                self.update(doc["uri"], doc["version"], doc["text"])
            elif method == "textDocument/didChange":
                doc, changes = params["textDocument"], params["contentChanges"]
                if doc["uri"] not in self.documents:
                    raise ValueError("Document is not open")
                if not changes or any("range" in change for change in changes):
                    raise ValueError("This server requires full document synchronization")
                self.update(doc["uri"], doc["version"], changes[-1]["text"])
            elif method == "textDocument/didClose":
                uri = params["textDocument"]["uri"]
                self.documents.pop(uri, None)
                self.send(method="textDocument/publishDiagnostics", params={"uri": uri, "diagnostics": []})
            elif method == "textDocument/formatting":
                doc = self.documents.get(params["textDocument"]["uri"])
                if doc is None:
                    raise ValueError("Document is not open")
                options = params.get("options")
                if (not isinstance(options, dict) or type(options.get("tabSize")) is not int
                        or options["tabSize"] < 1 or type(options.get("insertSpaces")) is not bool):
                    raise ValueError("Formatting options require a positive tabSize and boolean insertSpaces")
                # The versioned canonical profile takes precedence over
                # client indentation preferences; no workspace config is read.
                try:
                    formatted = format_source(doc.source)
                except CompileError as error:
                    self.send(id=identity, error={"code": -32803, "message": "Source could not be formatted",
                                                 "data": {"diagnostics": [error.diagnostic(doc.source)]}})
                    return None
                edits = [] if formatted == doc.source else [
                    {"range": source_range(doc.source, Span(0, len(doc.source))), "newText": formatted}]
                self.send(id=identity, result=edits)
            elif method in ("textDocument/hover", "textDocument/definition", "textDocument/documentSymbol"):
                doc = self.documents.get(params["textDocument"]["uri"])
                result = [] if method.endswith("documentSymbol") else None
                if doc and doc.analysis:
                    if method.endswith("documentSymbol"):
                        result = [{"name": item.name.text, "kind": 12 if hasattr(item, "params") else 23,
                                   "range": source_range(doc.source, item.span),
                                   "selectionRange": source_range(doc.source, item.name.span)}
                                  for item in [*doc.analysis.program.records, *doc.analysis.program.functions]]
                    else:
                        offset = offset_at(doc.source, params["position"])
                        refs = [r for r in doc.analysis.references
                                if offset is not None and r.span.start <= offset < r.span.end]
                        if refs:
                            ref = min(refs, key=lambda r: r.span.end - r.span.start)
                            result = ({"contents": {"kind": "plaintext", "value": ref.description},
                                       "range": source_range(doc.source, ref.span)} if method.endswith("hover")
                                      else {"uri": params["textDocument"]["uri"],
                                            "range": source_range(doc.source, ref.definition)}
                                      if ref.definition is not None else None)
                self.send(id=identity, result=result)
            elif request:
                self.send(id=identity, error={"code": -32601, "message": "Method not supported"})
        except (KeyError, TypeError, ValueError, UnicodeError) as error:
            if request:
                self.send(id=identity, error={"code": -32602, "message": str(error)})
            else:
                self.send(method="window/logMessage", params={"type": 1, "message": str(error)})
        return None


def serve(input_stream: BinaryIO, output_stream: BinaryIO) -> int:
    server = Server(output_stream)
    while True:
        try:
            message = read_message(input_stream)
        except (ValueError, UnicodeError, RecursionError) as error:
            server.send(id=None, error={"code": -32700, "message": str(error)})
            return 1
        if message is None:
            return 0 if server.shutdown else 1
        status = server.handle(message)
        if status is not None:
            return status
