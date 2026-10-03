"""Bounded stdio LSP with shared diagnostics, navigation and editor queries.

Documents are analyzed from editor-supplied text. The server never opens a URI,
executes a compiler subprocess, installs a dependency, or runs source programs.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import BinaryIO

from . import VERSION
from .completion import completion_items
from .document_changes import apply_changes
from .formatter import format_source
from .frontend import BUILTINS, KEYWORDS, SCALARS, Analysis, CompileError, Span, analyze, check_source, source_range
from .semantic_tokens import TOKEN_MODIFIERS, TOKEN_TYPES, semantic_tokens
from .signature_help import signature_help
import re

MAX_MESSAGE_BYTES = 1024 * 1024
MAX_DOCUMENTS = 32


class MessageError(ValueError):
    """A complete but invalid message; the stream remains synchronized."""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


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
    # The whole body was consumed, so framing is intact and the session can
    # continue after rejecting it.
    try:
        message = json.loads(body)
    except (ValueError, RecursionError) as error:
        raise MessageError(-32700, str(error)) from None
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        raise MessageError(-32600, "Expected a JSON-RPC 2.0 object")
    identity = message.get("id")
    if isinstance(identity, bool) or not isinstance(identity, (str, int, type(None))):
        raise MessageError(-32600, "Request id must be a string, integer, or null")
    pending = [(message, 1)]
    while pending:
        value, depth = pending.pop()
        if depth > 128:
            raise MessageError(-32600, "LSP JSON nesting exceeds limit")
        children = value.values() if isinstance(value, dict) else value if isinstance(value, list) else ()
        pending.extend((child, depth + 1) for child in children)
    try:
        json.dumps(message, ensure_ascii=False).encode("utf-8")
    except UnicodeEncodeError:
        raise MessageError(-32600, "LSP message contains an unpaired UTF-16 surrogate") from None
    return message


IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z_0-9]*\Z")
RESERVED = KEYWORDS | SCALARS | BUILTINS | {"str"}


def symbol_occurrences(doc: Document, point: dict) -> list[tuple[Span, bool]] | None:
    """Name spans of every use of the user-defined symbol at point, declaration flagged.

    Occurrences are grouped by the declaration the checker resolved them to,
    so a local and a same-named symbol elsewhere stay separate. Reference
    spans can include a borrow prefix (`&mut Counter`); only the trailing
    name is returned.
    """
    offset = offset_at(doc.source, point)
    refs = [r for r in doc.analysis.references if offset is not None and r.span.start <= offset < r.span.end]
    if not refs:
        return None
    target = min(refs, key=lambda r: r.span.end - r.span.start).definition
    if target is None:
        return None  # Builtins such as print have no source declaration.
    name = doc.source[target.start:target.end]
    spans = {Span(r.span.end - len(name), r.span.end) for r in doc.analysis.references if r.definition == target}
    spans.add(target)
    if any(doc.source[span.start:span.end] != name for span in spans):
        return None
    return [(span, span == target) for span in sorted(spans, key=lambda span: span.start)]


def rename_edits(doc: Document | None, uri: str, occurrences, new_name) -> dict:
    """A workspace edit, or an error when the rename would not check."""
    if occurrences is None:
        return {"error": {"code": -32803, "message": "No renameable symbol at this position"}}
    if not isinstance(new_name, str) or not IDENTIFIER.match(new_name) or new_name in RESERVED:
        return {"error": {"code": -32602, "message": "New name must be an ASCII identifier that is not reserved"}}
    source = doc.source
    for span, _ in reversed(occurrences):
        source = source[:span.start] + new_name + source[span.end:]
    try:
        analyze(source)
    except CompileError as error:
        return {"error": {"code": -32803, "message": f"Rename would not check: {error.code}: {error.message}"}}
    edits = [{"range": source_range(doc.source, span), "newText": new_name} for span, _ in occurrences]
    return {"result": {"changes": {uri: edits}}}


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
    synchronized: bool = True


class Server:
    def __init__(self, output: BinaryIO):
        self.output = output
        self.documents: dict[str, Document] = {}
        self.initialized = False
        self.shutdown = False

    def send(self, **fields):
        write_message(self.output, {"jsonrpc": "2.0", **fields})

    def document(self, uri):
        document = self.documents.get(uri)
        if document is not None and not document.synchronized:
            raise ValueError('Document requires a full replacement after a rejected change')
        return document

    def update(self, uri: str, version: int, source: str):
        if not isinstance(uri, str) or type(version) is not int or not isinstance(source, str):
            raise ValueError("Invalid document")
        previous = self.documents.get(uri)
        if previous and version <= previous.version:
            return
        if previous is None and len(self.documents) >= MAX_DOCUMENTS:
            raise ValueError("Open-document limit reached")
        result, errors = check_source(source)
        diagnostics = [error.diagnostic(source) for error in errors]
        self.documents[uri] = Document(source, version, result)
        self.send(method="textDocument/publishDiagnostics",
                  params={"uri": uri, "version": version, "diagnostics": diagnostics})

    def handle(self, message: dict) -> int | None:
        method, params = message.get("method"), message.get("params")
        if params is None:
            params = {}
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
                    "positionEncoding": "utf-16", "textDocumentSync": {"openClose": True, "change": 2},
                    "hoverProvider": True, "definitionProvider": True, "documentSymbolProvider": True,
                    "documentFormattingProvider": True, "referencesProvider": True, "renameProvider": True,
                    "completionProvider": {"resolveProvider": False, "triggerCharacters": ["."]},
                    "signatureHelpProvider": {"triggerCharacters": ["(", ","]},
                    "semanticTokensProvider": {"legend": {"tokenTypes": TOKEN_TYPES, "tokenModifiers": TOKEN_MODIFIERS},
                                               "full": True, "range": False},
                    "experimental": {"talvenProjectQuery": {"profile": "m1-local-modules-v1",
                                                              "source": "explicit-in-memory-bundle"},
                                     "talvenOutcomeContext": {"profile": "m2-concrete-outcomes-v1",
                                                              "source": "explicit-in-memory-source"}}},
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
            if method == 'talven/outcomeContext':
                from .outcomes import analyze_outcomes, outcome_context
                if not isinstance(params.get('source'), str):
                    raise ValueError('Outcome source must be a string')
                analysis = analyze_outcomes(params['source'])
                self.send(id=identity, result=outcome_context(analysis, params.get('maxBytes', 16384),
                                                           params.get('expectSourceHash')))
                return None
            if method == "talven/projectQuery":
                # An explicit source bundle permits cross-file navigation without
                # opening URIs or silently discovering filesystem dependencies.
                from .project import analyze_project, project_query
                project = analyze_project(params['entry'], params['sources'])
                if params.get('expectGraphHash') not in (None, project.identity()['graph_hash']):
                    raise CompileError('E0501', 'Project revision changed; supply fresh sources', Span(0, 0))
                result = project_query(project, params['file'], params['position'],
                                       params.get('kind', 'definition'), params.get('maxBytes', 16384))
                self.send(id=identity, result=result)
                return None
            if method == "textDocument/didOpen":
                doc = params["textDocument"]
                self.update(doc["uri"], doc["version"], doc["text"])
            elif method == "textDocument/didChange":
                doc, changes = params["textDocument"], params.get("contentChanges")
                uri, version = doc['uri'], doc['version']
                if not isinstance(uri, str) or type(version) is not int:
                    raise ValueError('Invalid document identity/version')
                previous = self.documents.get(uri)
                if previous is None:
                    raise ValueError("Document is not open")
                if version <= previous.version:
                    return None
                try:
                    source = apply_changes(previous.source if previous.synchronized else None, changes)
                except ValueError:
                    previous.synchronized, previous.analysis, previous.version = False, None, version
                    self.send(method='textDocument/publishDiagnostics', params={'uri': uri, 'diagnostics': []})
                    raise
                self.update(uri, version, source)
            elif method == "textDocument/didClose":
                uri = params["textDocument"]["uri"]
                self.documents.pop(uri, None)
                self.send(method="textDocument/publishDiagnostics", params={"uri": uri, "diagnostics": []})
            elif method == "textDocument/formatting":
                doc = self.document(params["textDocument"]["uri"])
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
            elif method == "textDocument/completion":
                doc = self.document(params["textDocument"]["uri"])
                if doc is None:
                    raise ValueError("Document is not open")
                offset = offset_at(doc.source, params["position"])
                if offset is None:
                    raise ValueError("Invalid completion position")
                self.send(id=identity, result=completion_items(doc.source, offset, doc.analysis, doc.version))
            elif method == "textDocument/semanticTokens/full":
                doc = self.document(params["textDocument"]["uri"])
                if doc is None:
                    raise ValueError("Document is not open")
                self.send(id=identity, result=semantic_tokens(doc.source, doc.analysis))
            elif method == "textDocument/signatureHelp":
                doc = self.document(params["textDocument"]["uri"])
                if doc is None:
                    raise ValueError("Document is not open")
                offset = offset_at(doc.source, params["position"])
                if offset is None:
                    raise ValueError("Invalid signature-help position")
                self.send(id=identity, result=signature_help(doc.source, offset, doc.analysis))
            elif method in ("textDocument/hover", "textDocument/definition", "textDocument/documentSymbol"):
                doc = self.document(params["textDocument"]["uri"])
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
            elif method in ("textDocument/references", "textDocument/rename"):
                uri = params["textDocument"]["uri"]
                doc = self.document(uri)
                occurrences = symbol_occurrences(doc, params["position"]) if doc and doc.analysis else None
                if method.endswith("references"):
                    include = (params.get("context") or {}).get("includeDeclaration", True)
                    result = None if occurrences is None else [
                        {"uri": uri, "range": source_range(doc.source, span)}
                        for span, declaration in occurrences if include or not declaration]
                    self.send(id=identity, result=result)
                else:
                    self.send(id=identity, **rename_edits(doc, uri, occurrences, params["newName"]))
            elif request:
                self.send(id=identity, error={"code": -32601, "message": "Method not supported"})
        except CompileError as error:
            if request:
                outcome_request = method == 'talven/outcomeContext'
                source = params['source'] if outcome_request else ''
                self.send(id=identity, error={"code": -32803,
                                             "message": "Outcome context failed" if outcome_request else "Project query failed",
                                             "data": {"diagnostics": [error.diagnostic(source)]}})
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
        except MessageError as error:
            server.send(id=None, error={"code": error.code, "message": str(error)})
            continue
        except (ValueError, UnicodeError, RecursionError) as error:
            server.send(id=None, error={"code": -32700, "message": str(error)})
            return 1
        if message is None:
            return 0 if server.shutdown else 1
        status = server.handle(message)
        if status is not None:
            return status
