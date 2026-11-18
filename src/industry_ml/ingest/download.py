"""Download files once and cache them under data/raw/."""
import hashlib
import logging
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)

USER_AGENT = "industry-ml research pipeline"

def fetch(url: str, dest: Path, refresh: bool = False, label: str | None = None) -> Path:
    """ Download Url to dest unless cached copy exists
        label is what gets logged instead of URL, 
        so URLs carrying an APi key never reach teh termina lor log files
    """
    name = label or url                         # label is logged instead of url as that has api key so logging url would write the key into files.
    if dest.exists() and not refresh:
        log.info("Using cached %s", dest.name)  # if file already in data/raw its used and nothhing downloaded
        return dest
        
    log.info("Downloading %s", name)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})   # User-agent tells server what program header is calling (This is research pipeline)
    with urllib.request.urlopen(request, timeout=60) as response:               # --refresh forces a fresh download (e.g. when there is a new month of published data)
        payload = response.read()                                               # timeout=60 gives up after a minute instead to waiting forever

    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_name(dest.name + ".part")  # writes a temp file [].json.part while it is being written in case the connection drops halfway through 
    partial.write_bytes(payload)                   # Without this a half-written file sits in cache and gets parsed through every run.
    partial.replace(dest)                          # Path.replace renames in a single step 
    return dest

def sha256(path: Path) -> str:                            # hash turns any input to fixed 256 bit fingerprint (SHA-256) written as 64 hexadecimal characters 
    return hashlib.sha256(path.read_bytes()).hexdigest()  # Same input gives same hass on any machine, changing one bit of input changes half the output bits 
# so raw.load_log stores one file as two loads with same hash is identical diff hashes means the soureces have changed . 
# Hashes only work on bytes, not text.
    