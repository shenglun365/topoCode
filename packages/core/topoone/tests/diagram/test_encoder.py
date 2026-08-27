"""PlantUML encoding - Python side.

Cross-language contract notes:
- The encoding wraps raw deflate bytes, so output depends on the zlib implementation.
  TS (node zlib) and Python (CPython zlib) are NOT byte-identical by design; the plantuml
  server decodes any valid variant.
- The real contract is decodability, verified end-to-end in test_api.py (round-trip
  through the live sidecar).
- This test pins the algorithm shape (alphabet, determinism, sensitivity to input).
"""

from topoone.diagram.encoder import encode

CODE = "@startuml\nAlice -> Bob: hello\nBob --> Alice: hi\n@enduml"


def test_only_url_safe_alphabet():
    assert encode(CODE), "empty encoding"
    assert all(c in "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_" for c in encode(CODE))


def test_deterministic():
    assert encode(CODE) == encode(CODE)


def test_sensitive_to_input():
    assert encode(CODE) != encode(CODE + "\n")


def test_empty_string_encodes():
    assert encode("")
