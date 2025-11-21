import os
import shutil
import requests
import zipfile
import io
import zlib
import gzip
import json
import re
from pathlib import Path
from flask import Flask, request, jsonify, send_file, render_template
from flask_cors import CORS
import threading
import uuid
import time

app = Flask(__name__)
CORS(app)

# Import the working repack module
import sys
sys.path.append('/app')  # Add current directory to path

# We'll use the working TencentPAKFile class from our tool for repacking only
from FIRST import TencentPAKFile

# GitHub raw file URLs
GITHUB_RAW_URL = "https://github.com/darksideyt762-hu/120fps-unlocker/raw/refs/heads/main/"
PAK_FILE_URL = GITHUB_RAW_URL + "game_patch_4.1.0.20546.pak"
UEXP_FILE_URL = GITHUB_RAW_URL + "000148.uexp"

# Use proper temp directory for Railway
TEMP_DIR = '/tmp/120fps_files'

# Store processing status
processing_status = {}

# XOR encryption keys
SIG2KEY = {
    bytes.fromhex("9DC7"): bytes.fromhex("E55B4ED1"),
    bytes.fromhex("9D81"): bytes.fromhex("E51D4ED1"),
}

# ─── XOR Functions ────────────────────────────────────────────────────────────

def is_sig_at(data: bytes, i: int):
    """Check if signature exists at position."""
    if i + 2 > len(data):
        return None
    return SIG2KEY.get(data[i:i+2], None)

def xor_decode_with_feedback(data: bytes) -> bytes:
    """Decode XOR encrypted data."""
    out = bytearray()
    key = None
    seg_pos = 0
    seg_start_out = 0
    i = 0
    while i < len(data):
        k = is_sig_at(data, i)
        if k is not None:
            key = k
            seg_pos = 0
            seg_start_out = len(out)
        if key is not None:
            if seg_pos < 4:
                o = data[i] ^ key[seg_pos]
            else:
                fb_index = seg_start_out + (seg_pos - 4)
                o = data[i] ^ out[fb_index]
            out.append(o)
            seg_pos += 1
        else:
            out.append(data[i])
        i += 1
    return bytes(out)

def xor_reencode_from_original(encoded_original: bytes, decoded_modified: bytes) -> bytes:
    """Re-encode modified data."""
    assert len(encoded_original) == len(decoded_modified)
    out_enc = bytearray()
    key = None
    seg_pos = 0
    seg_start_out = 0
    for i in range(len(decoded_modified)):
        k = is_sig_at(encoded_original, i)
        if k is not None:
            key = k
            seg_pos = 0
            seg_start_out = i
        if key is not None:
            if seg_pos < 4:
                b = decoded_modified[i] ^ key[seg_pos]
            else:
                fb_index = seg_start_out + (seg_pos - 4)
                b = decoded_modified[i] ^ decoded_modified[fb_index]
            out_enc.append(b)
            seg_pos += 1
        else:
            out_enc.append(decoded_modified[i])
    return bytes(out_enc)

def compress_by_mode(raw_bytes: bytes, mode: str) -> bytes:
    """Compress data using specified mode."""
    if mode == "zlib":
        return zlib.compress(raw_bytes, level=9)
    elif mode == "gzip":
        bio = io.BytesIO()
        with gzip.GzipFile(fileobj=bio, mode="wb") as gzf:
            gzf.write(raw_bytes)
        return bio.getvalue()
    return zlib.compress(raw_bytes, level=9)

# ─── Device String Replacement (Keep your working method) ─────────────────────

def extract_device_ids_from_uexp(content: bytes):
    """
    Extract all device IDs from the uexp file.
    Pattern: device_id followed by ���120� or similar markers
    """
    # Find all patterns like CPH2649, SM-X910, RMX5011, etc.
    # They appear between markers and before ���120�
    pattern = rb'([A-Z0-9\-|]+)\xef\xbf\xbd{3,4}120'
    matches = re.findall(pattern, content)

    device_ids = []
    for match in matches:
        # Clean up the match
        decoded = match.decode('utf-8', errors='ignore').strip()
        # Split by | to get individual device IDs
        ids = [id.strip() for id in decoded.split('|') if id.strip()]
        device_ids.extend(ids)

    return device_ids

def find_and_replace_device_by_length(content: bytes, device_name: str) -> tuple:
    """
    Find a device ID with matching length and replace it.
    Strategy: Find all device IDs, pick one with same length, replace it.
    """
    device_len = len(device_name)
    device_bytes = device_name.encode('utf-8')

    # Extract all device IDs from file
    print(f"🔍 Scanning file for device IDs with length {device_len}...")

    # Find all device ID patterns in the file
    # Pattern: alphanumeric device IDs that appear in the configuration
    pattern = rb'([A-Z0-9][A-Z0-9\-]{4,15})(?=\xef\xbf\xbd|\x00|\|)'
    matches = list(re.finditer(pattern, content))

    print(f"✅ Found {len(matches)} potential device IDs")

    # Find a matching length device
    for match in matches:
        existing_device = match.group(1)
        try:
            existing_str = existing_device.decode('utf-8')
            if len(existing_str) == device_len:
                print(f"✅ Found matching length device: '{existing_str}' ({len(existing_str)} chars)")
                print(f"   Replacing with: '{device_name}' ({device_len} chars)")

                # Replace this device ID
                new_content = content.replace(existing_device, device_bytes, 1)
                return new_content, True, existing_str
        except:
            continue

    # If no exact match found, try to replace any device ID with padding/truncation
    print(f"⚠️  No exact length match found. Trying flexible replacement...")

    # Find the first suitable device ID to replace (prefer similar lengths)
    for match in sorted(matches, key=lambda m: abs(len(m.group(1)) - device_len)):
        existing_device = match.group(1)
        try:
            existing_str = existing_device.decode('utf-8')
            existing_len = len(existing_str)

            print(f"   Trying to replace '{existing_str}' ({existing_len} chars)")

            if existing_len >= device_len:
                # Pad our device name to match length
                padded_device = device_bytes.ljust(existing_len, b'\x00')
                new_content = content.replace(existing_device, padded_device, 1)
                return new_content, True, existing_str
            else:
                # Truncate our device name
                truncated_device = device_bytes[:existing_len]
                new_content = content.replace(existing_device, truncated_device, 1)
                print(f"   ⚠️  Device name truncated to '{truncated_device.decode()}' to fit")
                return new_content, True, existing_str
        except:
            continue

    return content, False, None

def find_compressed_uexp_in_decoded(decoded_data: bytes, uexp_content: bytes) -> tuple:
    """
    Find where the compressed version of uexp_content exists in decoded PAK data.
    Returns (position, compressed_data, compression_mode) or None
    """
    # Try both zlib and gzip compression
    for mode_name, compress_func in [("zlib", lambda d: zlib.compress(d, level=9)), 
                                       ("gzip", lambda d: compress_by_mode(d, "gzip"))]:
        compressed = compress_func(uexp_content)
        pos = decoded_data.find(compressed)
        if pos != -1:
            print(f"✅ Found original compressed 000148.uexp at position {pos} (mode: {mode_name})")
            return pos, compressed, mode_name

    # Try with different compression levels
    print("🔍 Trying different compression levels...")
    for level in range(1, 10):
        compressed = zlib.compress(uexp_content, level=level)
        pos = decoded_data.find(compressed)
        if pos != -1:
            print(f"✅ Found at position {pos} with zlib level {level}")
            return pos, compressed, "zlib"

    return None, None, None

# ─── Main Processing with Tool Repack ─────────────────────────────────────────

def download_from_url(url, destination, job_id):
    """Download a file from URL."""
    filename = os.path.basename(destination)
    processing_status[job_id]['status'] = f"Downloading {filename}..."
    
    try:
        response = requests.get(url, stream=True, timeout=60)
        if response.status_code == 200:
            with open(destination, "wb") as file:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        file.write(chunk)
            print(f"✅ Downloaded: {filename}")
            return True
        else:
            print(f"❌ Failed to download: {url} - Status code: {response.status_code}")
            processing_status[job_id]['status'] = f"Failed to download {filename}"
            return False
    except Exception as e:
        print(f"❌ Error downloading {url}: {str(e)}")
        processing_status[job_id]['status'] = f"Error downloading {filename}: {str(e)}"
        return False

def process_files_with_tool_repack(device_name: str, job_id: str):
    """
    Main processing using your working 120FPS method + tool repack:
    1. Download PAK file
    2. Download 000148.uexp file  
    3. Modify 000148.uexp with device string (your working method)
    4. Use tool repack to apply the modification
    """
    try:
        os.makedirs(TEMP_DIR, exist_ok=True)
        job_dir = Path(TEMP_DIR) / job_id
        job_dir.mkdir(exist_ok=True)

        # Create folder structure for tool
        base_dir = job_dir / "FIRSTTOOL"
        base_dir.mkdir(exist_ok=True)
        
        # Create required folders
        folders = ['GAME_PATCH', 'MOD_UEXP', 'MODED_FILE']
        subfolders = ['INPUT', 'OUTPUT']
        
        for folder in folders:
            folder_path = base_dir / folder
            folder_path.mkdir(exist_ok=True)
            if folder == 'GAME_PATCH':
                for sub in subfolders:
                    (folder_path / sub).mkdir(exist_ok=True)
        
        (base_dir / 'MODED_FILE' / 'GAME_PATCH_MOD').mkdir(parents=True, exist_ok=True)

        # Download PAK file to tool input folder
        processing_status[job_id]['status'] = "Downloading game patch..."
        processing_status[job_id]['progress'] = 20
        
        pak_file_path = base_dir / 'GAME_PATCH' / 'INPUT' / 'game_patch_4.0.0.20332.pak'
        if not download_from_url(PAK_FILE_URL, pak_file_path, job_id):
            processing_status[job_id]['status'] = "Failed to download game patch"
            processing_status[job_id]['progress'] = 0
            return None

        # Download 000148.uexp file
        processing_status[job_id]['status'] = "Downloading device configuration..."
        processing_status[job_id]['progress'] = 40
        
        uexp_file_path = base_dir / '000148.uexp'
        if not download_from_url(UEXP_FILE_URL, uexp_file_path, job_id):
            processing_status[job_id]['status'] = "Failed to download device config"
            processing_status[job_id]['progress'] = 0
            return None

        # Read original 000148.uexp
        with open(uexp_file_path, "rb") as f:
            uexp_content = f.read()
        print(f"✅ Loaded 000148.uexp ({len(uexp_content)} bytes)")

        # Modify 000148.uexp with device string (your working method)
        processing_status[job_id]['status'] = f"Adding 120FPS for {device_name}..."
        processing_status[job_id]['progress'] = 60
        
        print(f"🔧 Modifying device string to: {device_name} ({len(device_name)} chars)")
        modified_uexp, replaced, old_device = find_and_replace_device_by_length(uexp_content, device_name)

        if not replaced:
            processing_status[job_id]['status'] = "Could not find suitable device ID to replace"
            processing_status[job_id]['progress'] = 0
            print("❌ Could not find suitable device ID to replace in 000148.uexp")
            return None

        print(f"✅ Successfully replaced '{old_device}' with '{device_name}'")

        # Save modified uexp to MOD_UEXP folder with correct path structure
        mod_uexp_path = base_dir / 'MOD_UEXP' / 'Content' / 'MultiRegion' / 'Content' / 'IN' / 'CSV' / 'Client120FPSMapping.uexp'
        mod_uexp_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(mod_uexp_path, "wb") as f:
            f.write(modified_uexp)
        print(f"✅ Saved modified 000148.uexp to MOD_UEXP folder")

        # Use tool repack to apply the modification
        processing_status[job_id]['status'] = "Repacking with tool..."
        processing_status[job_id]['progress'] = 80
        
        try:
            print("🔄 Using tool repack...")
            mod_folder = base_dir / 'MOD_UEXP'
            output_pak = base_dir / 'MODED_FILE' / 'GAME_PATCH_MOD' / f"game_patch_4.0.0.20332_120fps.pak"
            
            # Use the proven repack method from the tool
            pak_instance = TencentPAKFile(pak_file_path, is_od_pack=False)
            pak_instance.repack(mod_folder, output_pak, "Game Patch with 120FPS")
            print("✅ Tool repack complete!")
        except Exception as e:
            print(f"❌ Tool repack failed: {e}")
            processing_status[job_id]['status'] = f"Failed to repack: {str(e)}"
            processing_status[job_id]['progress'] = 0
            return None

        # Create ZIP file with the repacked PAK
        processing_status[job_id]['status'] = "Creating download package..."
        processing_status[job_id]['progress'] = 90
        
        zip_file_path = job_dir / f"{device_name}_120FPS.zip"
        with zipfile.ZipFile(zip_file_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            zipf.write(output_pak, arcname="game_patch_4.0.0.20332.pak")
        
        print(f"✅ Created ZIP: {zip_file_path.name}")

        processing_status[job_id]['status'] = "Complete!"
        processing_status[job_id]['progress'] = 100
        processing_status[job_id]['download_url'] = f"/download_file/{job_id}"
        processing_status[job_id]['filename'] = f"{device_name}_120FPS.zip"
        
        return zip_file_path

    except Exception as e:
        processing_status[job_id]['status'] = f"Error: {str(e)}"
        processing_status[job_id]['progress'] = 0
        print(f"Error in process_files: {e}")
        import traceback
        traceback.print_exc()
        return None

# ─── Flask Routes ─────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/start_processing', methods=['POST'])
def start_processing():
    data = request.get_json()
    device_name = data.get('device_name', '').strip().upper()
    
    if not device_name:
        return jsonify({'error': 'Please enter a device model'}), 400
    
    if len(device_name) < 5 or len(device_name) > 20:
        return jsonify({'error': 'Device model should be between 5-20 characters'}), 400
    
    # Generate unique job ID
    job_id = str(uuid.uuid4())
    processing_status[job_id] = {
        'status': 'Starting...',
        'progress': 0,
        'device_name': device_name,
        'download_url': None,
        'filename': None,
        'created_time': time.time()
    }
    
    # Start processing in background thread
    thread = threading.Thread(target=process_files_with_tool_repack, args=(device_name, job_id))
    thread.daemon = True
    thread.start()
    
    return jsonify({'job_id': job_id})

@app.route('/status/<job_id>')
def get_status(job_id):
    status = processing_status.get(job_id, {'status': 'Not found', 'progress': 0})
    return jsonify(status)

@app.route('/download_file/<job_id>')
def download_result(job_id):
    status = processing_status.get(job_id)
    if not status or not status.get('filename'):
        return "File not found", 404
    
    filename = status['filename']
    file_path = Path(TEMP_DIR) / job_id / filename
    
    if not file_path.exists():
        return "File not found", 404
    
    try:
        # Send file to user
        response = send_file(file_path, as_attachment=True, download_name=filename)
        
        # Schedule cleanup after download is complete
        def cleanup_after_download():
            import time
            time.sleep(2)  # Wait a bit to ensure download started
            try:
                job_dir = Path(TEMP_DIR) / job_id
                if job_dir.exists():
                    shutil.rmtree(job_dir, ignore_errors=True)
                    print(f"✅ Cleaned up temporary files for job: {job_id}")
                if job_id in processing_status:
                    del processing_status[job_id]
            except Exception as e:
                print(f"⚠️ Error cleaning up {job_dir}: {e}")
        
        # Run cleanup in background thread
        cleanup_thread = threading.Thread(target=cleanup_after_download)
        cleanup_thread.daemon = True
        cleanup_thread.start()
        
        return response
        
    except Exception as e:
        return f"Error serving file: {str(e)}", 500

# Cleanup old files periodically
def cleanup_old_files():
    """Clean up files older than 1 hour"""
    while True:
        try:
            now = time.time()
            temp_dir = Path(TEMP_DIR)
            if temp_dir.exists():
                for job_id in temp_dir.iterdir():
                    if job_id.is_dir():
                        # Remove directories older than 1 hour
                        if now - job_id.stat().st_ctime > 3600:
                            shutil.rmtree(job_id, ignore_errors=True)
                            if job_id.name in processing_status:
                                del processing_status[job_id.name]
                            print(f"🧹 Cleaned up old job: {job_id.name}")
        except Exception as e:
            print(f"⚠️ Error in cleanup: {e}")
        time.sleep(3600)  # Check every hour

if __name__ == '__main__':
    # Ensure temp directory exists
    os.makedirs(TEMP_DIR, exist_ok=True)
    
    # Start cleanup thread
    cleanup_thread = threading.Thread(target=cleanup_old_files)
    cleanup_thread.daemon = True
    cleanup_thread.start()
    
    # Get port from environment variable or default to 5000
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
