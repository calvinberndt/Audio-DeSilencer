# Audio-DeSilencer Dead Air Detection

This is a Python implementation of dead air detection that leverages the Audio-DeSilencer library to analyze audio files directly from the database.

## Features

- **Audio-based dead air detection** using silence detection algorithms
- **PostgreSQL integration** to fetch audio content from the database
- **Web UI** for interactive visualization and analysis
- **CLI tool** for batch processing
- **Configurable parameters** for detection thresholds

## Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Ensure your `.env` file contains the database credentials:
```
DEV_DB_HOST=your_host
DEV_DB_USER=your_user
DEV_DB_PASS=your_password
DEV_DB_NAME=your_database
```

## Usage

### Command Line Interface

Process a single call:
```bash
python main.py --call-id 12345
```

Process a batch of calls:
```bash
python main.py --limit 100
```

Process with custom threshold:
```bash
python main.py --limit 50 --threshold 5.0 --skip-start 15.0
```

View statistics:
```bash
python main.py --stats-only
```

Available parameters:
- `--threshold`: Dead air threshold in seconds (default: 3.0)
- `--skip-start`: Seconds to skip from start (default: 10.0)
- `--skip-end`: Seconds to skip from end (default: 10.0)
- `--min-amplitude`: Minimum amplitude threshold in dBFS (default: -30.0)
- `--reprocess`: Reprocess calls that have already been evaluated

### Web Interface

Start the web server:
```bash
python web_server.py
```

Or with custom port:
```bash
python web_server.py --port 5000 --debug
```

Then open your browser to `http://localhost:3000` (or your custom port).

## How It Works

1. **Audio Fetching**: The system fetches WAV audio content stored as bytea in the PostgreSQL database
2. **Silence Detection**: Uses pydub's silence detection to identify gaps in the audio
3. **Dead Air Analysis**: Gaps exceeding the threshold within evaluation boundaries are marked as dead air
4. **Visualization**: The web UI displays:
   - Audio waveform with WaveSurfer.js
   - Dead air gaps highlighted in red
   - Skip boundaries shown in gray
   - Adjustable parameters with real-time analysis

## Differences from JavaScript Version

- Uses pydub instead of node-wav for audio processing
- Flask instead of Express for web server
- Audio-DeSilencer's proven silence detection algorithms
- Stores evaluations with `context='audio_analysis'` to distinguish from transcript-based detection

## API Endpoints

- `GET /api/call/:id` - Get call data
- `GET /api/audio/:id` - Stream audio content
- `POST /api/analyze/:id` - Run analysis with custom parameters
- `GET /api/stats` - Get overall statistics

## Database Schema

The system uses the existing tables:
- `dead_air.transcriptions_gemini` - Contains audio_content and transcriptions
- `dead_air.evaluation_gemini` - Stores analysis results

Audio evaluations are stored with:
- `transcription_id` = `audio_{call_id}`
- `context` = `'audio_analysis'`