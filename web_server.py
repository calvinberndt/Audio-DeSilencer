#!/usr/bin/env python3
"""
Web server for Audio-DeSilencer Dead Air Detection
Provides REST API and serves web UI for visualization
"""

from flask import Flask, jsonify, request, send_from_directory, Response, make_response
from flask_cors import CORS
from database_connector import DatabaseConnector
from audio_desilencer.audio_processor import AudioProcessor
import tempfile
import os
import json
from datetime import datetime, timedelta
import numpy as np
from scipy import signal
import wave
import struct
from functools import lru_cache
import hashlib

app = Flask(__name__, static_folder='web_ui')
CORS(app)

# Database connection
db = DatabaseConnector()

# In-memory cache for audio files (limited to 10 files)
audio_cache = {}
CACHE_MAX_SIZE = 10
CACHE_DURATION = timedelta(minutes=15)


@app.before_request
def before_request():
    """Ensure database connection before each request"""
    if not db.connection or db.connection.closed:
        db.connect()


@app.teardown_appcontext
def teardown_db(error):
    """Clean up database connection"""
    if error:
        print(f"Error during request: {error}")


# Serve static files
@app.route('/')
def index():
    """Serve the main web UI"""
    return send_from_directory('web_ui', 'index.html')


@app.route('/<path:path>')
def serve_static(path):
    """Serve static files"""
    return send_from_directory('web_ui', path)


# API Routes

@app.route('/api/call/<int:call_id>', methods=['GET'])
def get_call_data(call_id):
    """Get call data including transcription"""
    try:
        record = db.fetch_audio_content(call_id)
        
        if not record:
            return jsonify({'error': 'Call not found'}), 404
        
        return jsonify({
            'call_id': record['call_id'],
            'transcription': record['transcription'],
            'human_grade': record['human_grade'],
            'has_audio': bool(record.get('audio_content'))
        })
    
    except Exception as e:
        print(f"Error fetching call: {e}")
        return jsonify({'error': 'Failed to fetch call data'}), 500


def get_cached_audio(call_id):
    """Get audio from cache or fetch from database"""
    # Check if audio is in cache and not expired
    if call_id in audio_cache:
        cached_item = audio_cache[call_id]
        if datetime.now() - cached_item['timestamp'] < CACHE_DURATION:
            print(f"Serving audio for call_id {call_id} from cache")
            return cached_item['data']
        else:
            # Remove expired cache entry
            del audio_cache[call_id]
    
    # Fetch from database
    record = db.fetch_audio_content(call_id)
    if not record or not record.get('audio_content'):
        return None
    
    audio_bytes = record['audio_content']
    
    # Convert memoryview to bytes if needed (PostgreSQL bytea returns memoryview)
    if isinstance(audio_bytes, memoryview):
        audio_bytes = bytes(audio_bytes)
        print(f"Converted memoryview to bytes for call_id {call_id}")
    
    # Add to cache
    # If cache is full, remove oldest entry
    if len(audio_cache) >= CACHE_MAX_SIZE:
        oldest_key = min(audio_cache.keys(), 
                        key=lambda k: audio_cache[k]['timestamp'])
        del audio_cache[oldest_key]
    
    audio_cache[call_id] = {
        'data': audio_bytes,
        'timestamp': datetime.now()
    }
    
    print(f"Cached audio for call_id {call_id} (type: {type(audio_bytes)})")
    return audio_bytes


@app.route('/api/audio/<int:call_id>', methods=['GET'])
def stream_audio(call_id):
    """Stream audio content for a call with caching and ETags"""
    try:
        # Get audio from cache or database
        audio_bytes = get_cached_audio(call_id)
        
        if not audio_bytes:
            return jsonify({'error': 'Audio not found'}), 404
        
        # Ensure we have bytes, not memoryview
        if isinstance(audio_bytes, memoryview):
            audio_bytes = bytes(audio_bytes)
            print(f"Converted memoryview to bytes in stream_audio for call_id {call_id}")
        
        print(f"Streaming audio for call_id {call_id} (type: {type(audio_bytes)}, size: {len(audio_bytes)})")
        
        # Generate ETag based on content hash
        etag = hashlib.md5(audio_bytes[:1000]).hexdigest()  # Hash first 1KB for speed
        
        # Check if client has the same version
        if request.headers.get('If-None-Match') == etag:
            return '', 304  # Not Modified
        
        # Create response with caching headers
        response = make_response(audio_bytes)
        response.headers['Content-Type'] = 'audio/wav'
        response.headers['Content-Length'] = str(len(audio_bytes))
        response.headers['ETag'] = etag
        response.headers['Cache-Control'] = 'private, max-age=3600'  # Cache for 1 hour
        response.headers['Accept-Ranges'] = 'bytes'  # Support partial requests
        
        # Handle range requests for faster seeking
        range_header = request.headers.get('Range')
        if range_header:
            # Parse range header
            range_match = range_header.replace('bytes=', '').split('-')
            start = int(range_match[0]) if range_match[0] else 0
            end = int(range_match[1]) if range_match[1] else len(audio_bytes) - 1
            
            # Return partial content
            response = make_response(audio_bytes[start:end + 1])
            response.headers['Content-Type'] = 'audio/wav'
            response.headers['Content-Range'] = f'bytes {start}-{end}/{len(audio_bytes)}'
            response.headers['Content-Length'] = str(end - start + 1)
            response.status_code = 206  # Partial Content
        
        return response
    
    except Exception as e:
        print(f"Error streaming audio: {e}")
        return jsonify({'error': 'Failed to stream audio'}), 500


@app.route('/api/analyze/<int:call_id>', methods=['POST'])
def analyze_call(call_id):
    """Analyze call with custom parameters"""
    try:
        params = request.json or {}
        
        # Debug parameters received
        print(f"DEBUG - Parameters received for call_id {call_id}:")
        print(f"  Raw params: {params}")
        print(f"  Request content type: {request.content_type}")
        print(f"  Request data: {request.data}")
        
        # Get audio from cache first
        audio_bytes = get_cached_audio(call_id)
        if not audio_bytes:
            return jsonify({'error': 'Audio not found'}), 404
        
        # Get call metadata
        record = db.fetch_audio_content(call_id)
        if not record:
            return jsonify({'error': 'Call not found'}), 404
        
        # Convert audio to AudioSegment
        audio_segment = db.convert_audio_to_pydub(audio_bytes)
        
        # Create temporary file for AudioProcessor
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp_file:
            temp_path = tmp_file.name
            audio_segment.export(temp_path, format='wav')
        
        try:
            # Create AudioProcessor instance
            processor = AudioProcessor(temp_path)
            
            # Extract parameters with defaults
            threshold_seconds = params.get('thresholdSeconds', 3.0)
            skip_start_seconds = params.get('skipStartSeconds', 10.0)
            skip_end_seconds = params.get('skipEndSeconds', 10.0)
            min_amplitude_dbfs = params.get('minAmplitudeDbfs', -30.0)
            
            # Debug extracted parameters
            print(f"DEBUG - Extracted parameters:")
            print(f"  threshold_seconds: {threshold_seconds}")
            print(f"  skip_start_seconds: {skip_start_seconds}")
            print(f"  skip_end_seconds: {skip_end_seconds}")
            print(f"  min_amplitude_dbfs: {min_amplitude_dbfs}")
            
            # Detect dead air
            dead_air_result = processor.detect_dead_air(
                min_silence_len=int(threshold_seconds * 1000),
                threshold=int(min_amplitude_dbfs),
                skip_start_ms=int(skip_start_seconds * 1000),
                skip_end_ms=int(skip_end_seconds * 1000)
            )
            
            # Generate energy data for visualization
            energy_data = generate_energy_data(audio_segment)
            
            # Determine if call passed or failed
            passed = dead_air_result['total_gaps'] == 0
            
            # Debug logging
            print(f"DEBUG - Call {call_id}:")
            print(f"  Total gaps found: {dead_air_result['total_gaps']}")
            print(f"  Total dead air seconds: {dead_air_result['total_dead_air_seconds']}")
            print(f"  Passed calculation: {passed}")
            print(f"  Threshold used: {threshold_seconds}s")
            
            # Format timestamps for found_references
            formatted_gaps = []
            for gap in dead_air_result['gaps']:
                # Convert seconds to MM:SS format
                start_minutes = int(gap['start_time'] // 60)
                start_seconds = int(gap['start_time'] % 60)
                end_minutes = int(gap['end_time'] // 60)
                end_seconds = int(gap['end_time'] % 60)
                
                formatted_gaps.append({
                    'duration': gap['duration'],
                    'start_time': gap['start_time'],
                    'end_time': gap['end_time'],
                    'start_formatted': f"[{start_minutes:02d}:{start_seconds:02d}]",
                    'end_formatted': f"[{end_minutes:02d}:{end_seconds:02d}]"
                })
            
            # Build explanation like transcript version
            if passed:
                explanation = f"No dead air gaps exceeding {threshold_seconds} seconds found in the evaluated portion of the call."
                improvement_suggestion = None
            else:
                gap_descriptions = []
                for gap in formatted_gaps[:4]:  # Show first 4 gaps
                    gap_descriptions.append(
                        f"{gap['start_formatted']} to {gap['end_formatted']} ({gap['duration']:.1f}s)"
                    )
                
                explanation = (f"Found {dead_air_result['total_gaps']} dead air gap(s) exceeding "
                             f"{threshold_seconds} seconds ({dead_air_result['total_gaps']} unexpected). "
                             f"Gaps: {'; '.join(gap_descriptions)}")
                if dead_air_result['total_gaps'] > 4:
                    explanation += f"; ... and {dead_air_result['total_gaps'] - 4} more"
                    
                improvement_suggestion = "Reduce silence periods between utterances to maintain call flow and engagement."
            
            # Create database evaluation format
            db_evaluation = {
                'call_id': call_id,
                'transcription_id': call_id,  # Use call_id as transcription_id
                'intern_ai_grade': 'Yes' if passed else 'No',  # Yes = good, No = has dead air
                'score': 3 if passed else 0,
                'max_score': 3,
                'criteria': f'Dead Air Detection (>{threshold_seconds} seconds)',
                'passed': passed,
                'explanation': explanation,
                'improvement_suggestion': improvement_suggestion,
                'found_references': formatted_gaps,
                'context': (f"Skip end: {skip_end_seconds}s, Skip start: {skip_start_seconds}s, "
                          f"Threshold: {threshold_seconds}s, Audio analysis: Yes (WAV), "
                          f"Amplitude threshold: {min_amplitude_dbfs} dBFS"),
                'original_transcription': record.get('transcription', '')
            }
            
            # Save to database using existing connection
            success = False  # Initialize to ensure it's always defined
            try:
                print(f"DEBUG - Attempting to save evaluation for call_id: {call_id}")
                print(f"DEBUG - DB evaluation data structure: {list(db_evaluation.keys())}")
                
                success = db.insert_evaluation(db_evaluation)
                
                if success:
                    print(f"SUCCESS - Saved audio evaluation for call_id: {call_id}")
                else:
                    print(f"FAILED - Failed to save audio evaluation for call_id: {call_id}")
            except Exception as e:
                print(f"ERROR - Exception saving evaluation: {e}")
                import traceback
                traceback.print_exc()
                success = False
                
            print(f"DEBUG - Final success value: {success}")
            
            # Format response for UI
            ui_evaluation = {
                'call_id': call_id,
                'human_grade': record['human_grade'],
                'ai_grade': 'Yes' if passed else 'No',  # Yes = passed, No = failed (has dead air)
                'passed': passed,
                'gap_count': dead_air_result['total_gaps'],
                'found_references': dead_air_result['gaps'],
                'total_dead_air_seconds': dead_air_result['total_dead_air_seconds'],
                'evaluation_boundaries': dead_air_result['evaluation_boundaries'],
                'audio_duration': dead_air_result['audio_duration_seconds'],
                'saved_to_database': success
            }
            
            # Debug UI evaluation
            print(f"DEBUG - UI evaluation for call_id {call_id}:")
            print(f"  ai_grade: {ui_evaluation['ai_grade']}")
            print(f"  passed: {ui_evaluation['passed']}")
            print(f"  gap_count: {ui_evaluation['gap_count']}")
            print(f"  saved_to_database: {ui_evaluation['saved_to_database']}")
            
            # Add audio analysis data
            audio_analysis_data = {
                'threshold': min_amplitude_dbfs,
                'energyData': energy_data
            }
            
            return jsonify({
                'evaluation': ui_evaluation,
                'audioAnalysisData': audio_analysis_data,
                'parameters': params
            })
            
        finally:
            # Clean up temp file
            if os.path.exists(temp_path):
                os.unlink(temp_path)
    
    except Exception as e:
        print(f"Error analyzing call: {e}")
        return jsonify({'error': f'Failed to analyze call: {str(e)}'}), 500


@app.route('/api/stats', methods=['GET'])
def get_statistics():
    """Get overall statistics for audio-based evaluations"""
    try:
        stats = db.get_evaluation_statistics()
        return jsonify(stats)
    
    except Exception as e:
        print(f"Error fetching stats: {e}")
        return jsonify({'error': 'Failed to fetch statistics'}), 500


def generate_energy_data(audio_segment, samples_per_second=100):
    """
    Generate energy/amplitude data for visualization
    
    Args:
        audio_segment: pydub AudioSegment
        samples_per_second: Number of energy samples per second
        
    Returns:
        List of energy values
    """
    # Convert to mono if stereo
    if audio_segment.channels > 1:
        audio_segment = audio_segment.set_channels(1)
    
    # Get raw audio data
    samples = np.array(audio_segment.get_array_of_samples())
    sample_rate = audio_segment.frame_rate
    
    # Calculate window size for desired samples per second
    window_size = int(sample_rate / samples_per_second)
    
    # Calculate RMS energy for each window
    energy_values = []
    for i in range(0, len(samples), window_size):
        window = samples[i:i + window_size]
        if len(window) > 0:
            # RMS (Root Mean Square) energy
            rms = np.sqrt(np.mean(window.astype(np.float64) ** 2))
            # Normalize to 0-1 range (assuming 16-bit audio)
            normalized = rms / 32768.0
            energy_values.append(float(normalized))
    
    return energy_values


def main():
    """Run the web server"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Audio Dead Air Detection Web Server')
    parser.add_argument('--port', type=int, default=3000, help='Port to run server on')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to')
    parser.add_argument('--debug', action='store_true', help='Run in debug mode')
    
    args = parser.parse_args()
    
    # Connect to database
    try:
        db.connect()
        print("Connected to database")
    except Exception as e:
        print(f"Failed to connect to database: {e}")
        return
    
    print(f"Starting Audio Dead Air Detection Web Server on http://{args.host}:{args.port}")
    
    try:
        app.run(host=args.host, port=args.port, debug=args.debug)
    except KeyboardInterrupt:
        print("\nShutting down server...")
    finally:
        db.disconnect()


if __name__ == '__main__':
    main()