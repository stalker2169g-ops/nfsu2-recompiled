#!/usr/bin/env python3
"""Receive an owner-supplied executable encrypted to this ephemeral runner.
Only the public key and encrypted input metadata are written to GitHub.
No private key, plaintext executable or generated C is committed or uploaded.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

repo = os.environ["GITHUB_REPOSITORY"]
run_id = os.environ["GITHUB_RUN_ID"]
branch = "build-input-" + run_id
root = "https://api.github.com/repos/" + repo
token = os.environ["GH_TOKEN"]

def api(path, method="GET", data=None):
    body = None if data is None else json.dumps(data).encode()
    request = urllib.request.Request(
        root + path, data=body, method=method,
        headers={"Authorization": "Bearer " + token,
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)

private_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
public_key = private_key.public_key().public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
).decode()
api("/git/refs", "POST", {"ref": "refs/heads/" + branch,
                         "sha": os.environ["GITHUB_SHA"]})
session = {"run_id": run_id, "public_key_pem": public_key,
           "algorithm": "RSA-OAEP-SHA256+AES-256-GCM+zlib"}
api("/contents/session.json", "PUT", {
    "branch": branch, "message": "build: publish ephemeral input public key",
    "content": base64.b64encode(json.dumps(session).encode()).decode()})
print("Public input session ready on branch " + branch, flush=True)

deadline = time.monotonic() + 1200
while time.monotonic() < deadline:
    try:
        item = api("/contents/payload.json?ref=" + urllib.parse.quote(branch))
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
        time.sleep(15)
        continue
    manifest = json.loads(base64.b64decode(item["content"]))
    if str(manifest["run_id"]) != run_id:
        raise RuntimeError("Input belongs to a different build session")
    blob = api("/git/blobs/" + manifest["blob_sha"])
    envelope = json.loads(base64.b64decode(blob["content"]))
    decode = lambda name: base64.b64decode(envelope[name], validate=True)
    key = private_key.decrypt(
        decode("key"), padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),
                                    algorithm=hashes.SHA256(), label=None))
    compressed = AESGCM(key).decrypt(decode("nonce"), decode("ciphertext"),
                                    run_id.encode())
    data = zlib.decompress(compressed)
    actual = hashlib.sha256(data).hexdigest()
    if len(data) != 4800512 or actual != manifest["sha256"]:
        raise RuntimeError("Input length/hash mismatch")
    if not data.startswith(b"MZ"):
        raise RuntimeError("Input is not a PE executable")
    Path("work").mkdir(exist_ok=True)
    Path("work/SPEED2.EXE").write_bytes(data)
    print("Verified owner input: " + actual, flush=True)
    break
else:
    raise RuntimeError("Timed out waiting for encrypted build input")
