import WaveSurfer from 'https://unpkg.com/wavesurfer.js@7/dist/wavesurfer.esm.js';
import RegionsPlugin from 'https://unpkg.com/wavesurfer.js@7/dist/plugins/regions.esm.js';
import TimelinePlugin from 'https://unpkg.com/wavesurfer.js@7/dist/plugins/timeline.esm.js';

// Global variables
let wavesurfer = null;
let regions = null;
let currentCallId = null;
let currentCallData = null;

// DOM elements
const elements = {
    callId: document.getElementById('callId'),
    loadCall: document.getElementById('loadCall'),
    runAnalysis: document.getElementById('runAnalysis'),
    
    // Parameter inputs
    thresholdSeconds: document.getElementById('thresholdSeconds'),
    skipStartSeconds: document.getElementById('skipStartSeconds'),
    skipEndSeconds: document.getElementById('skipEndSeconds'),
    minAmplitudeDbfs: document.getElementById('minAmplitudeDbfs'),
    
    // Parameter value displays
    thresholdValue: document.getElementById('thresholdValue'),
    skipStartValue: document.getElementById('skipStartValue'),
    skipEndValue: document.getElementById('skipEndValue'),
    minAmplitudeValue: document.getElementById('minAmplitudeValue'),
    
    // Results
    resultSummary: document.getElementById('resultSummary'),
    humanGrade: document.getElementById('humanGrade'),
    aiGrade: document.getElementById('aiGrade'),
    matchStatus: document.getElementById('matchStatus'),
    gapsFound: document.getElementById('gapsFound'),
    totalDeadAir: document.getElementById('totalDeadAir'),
    audioDuration: document.getElementById('audioDuration'),
    databaseStatus: document.getElementById('databaseStatus'),
    
    // Audio controls
    playPauseBtn: document.getElementById('playPauseBtn'),
    playPauseIcon: document.getElementById('playPauseIcon'),
    stopBtn: document.getElementById('stopBtn'),
    currentTime: document.getElementById('currentTime'),
    totalTime: document.getElementById('totalTime'),
    
    // Loading elements
    waveformLoading: document.getElementById('waveformLoading'),
    loadingProgressBar: document.getElementById('loadingProgressBar'),
    loadingProgressText: document.getElementById('loadingProgressText'),
    
    // Other
    transcription: document.getElementById('transcription'),
    gapsDetail: document.getElementById('gapsDetail'),
    gapsList: document.getElementById('gapsList')
};

// Initialize parameter displays
function initializeParameterDisplays() {
    elements.thresholdSeconds.addEventListener('input', (e) => {
        elements.thresholdValue.textContent = parseFloat(e.target.value).toFixed(1);
    });
    
    elements.skipStartSeconds.addEventListener('input', (e) => {
        elements.skipStartValue.textContent = e.target.value;
    });
    
    elements.skipEndSeconds.addEventListener('input', (e) => {
        elements.skipEndValue.textContent = e.target.value;
    });
    
    elements.minAmplitudeDbfs.addEventListener('input', (e) => {
        elements.minAmplitudeValue.textContent = e.target.value;
    });
}

// Format time in MM:SS
function formatTime(seconds) {
    const minutes = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${minutes}:${secs.toString().padStart(2, '0')}`;
}

// Initialize WaveSurfer
function initializeWaveSurfer() {
    // Destroy existing instance if any
    if (wavesurfer) {
        wavesurfer.destroy();
    }
    
    // Show loading indicator
    elements.waveformLoading.style.display = 'flex';
    elements.loadingProgressBar.style.width = '0%';
    elements.loadingProgressText.textContent = '0%';
    
    // Create regions plugin
    regions = RegionsPlugin.create();
    
    // Create timeline plugin
    const timeline = TimelinePlugin.create();
    
    // Initialize WaveSurfer with optimizations
    wavesurfer = WaveSurfer.create({
        container: '#waveform',
        waveColor: '#3498db',
        progressColor: '#2980b9',
        cursorColor: '#e74c3c',
        barWidth: 2,
        barRadius: 3,
        responsive: true,
        height: 200,
        normalize: true,
        backend: 'WebAudio',  // Use WebAudio for better performance
        mediaControls: false,
        partialRender: true,  // Only render visible portion
        hideScrollbar: true,
        plugins: [regions, timeline]
    });
    
    // Track loading progress
    wavesurfer.on('loading', (percent) => {
        elements.loadingProgressBar.style.width = percent + '%';
        elements.loadingProgressText.textContent = percent + '%';
    });
    
    // Update time display
    wavesurfer.on('audioprocess', () => {
        elements.currentTime.textContent = formatTime(wavesurfer.getCurrentTime());
    });
    
    wavesurfer.on('ready', () => {
        // Hide loading indicator
        elements.waveformLoading.style.display = 'none';
        
        elements.totalTime.textContent = formatTime(wavesurfer.getDuration());
        elements.playPauseBtn.disabled = false;
        elements.stopBtn.disabled = false;
    });
    
    wavesurfer.on('error', (error) => {
        elements.waveformLoading.style.display = 'none';
        console.error('WaveSurfer error:', error);
        console.error('Error details:', error.stack || error);
        alert(`Error loading audio waveform: ${error.message || error}`);
    });
    
    wavesurfer.on('play', () => {
        elements.playPauseIcon.textContent = '⏸️';
        elements.playPauseBtn.innerHTML = '<span id="playPauseIcon">⏸️</span> Pause';
    });
    
    wavesurfer.on('pause', () => {
        elements.playPauseIcon.textContent = '▶️';
        elements.playPauseBtn.innerHTML = '<span id="playPauseIcon">▶️</span> Play';
    });
}

// Load call data
async function loadCall() {
    const callId = parseInt(elements.callId.value);
    if (!callId) {
        alert('Please enter a call ID');
        return;
    }
    
    try {
        // Show loading state
        elements.loadCall.disabled = true;
        elements.loadCall.textContent = 'Loading...';
        
        // Fetch call data
        const response = await fetch(`/api/call/${callId}`);
        if (!response.ok) {
            throw new Error('Call not found');
        }
        
        currentCallData = await response.json();
        currentCallId = callId;
        
        // Display transcription
        elements.transcription.textContent = currentCallData.transcription || 'No transcription available';
        
        // Check if audio is available
        if (!currentCallData.has_audio) {
            alert('No audio content available for this call');
            elements.runAnalysis.disabled = true;
            return;
        }
        
        // Initialize WaveSurfer and load audio
        try {
            initializeWaveSurfer();
            console.log(`Loading audio from: /api/audio/${callId}`);
            wavesurfer.load(`/api/audio/${callId}`);
        } catch (error) {
            console.error('Error initializing WaveSurfer:', error);
            alert(`Error initializing audio: ${error.message}`);
        }
        
        // Enable analysis button
        elements.runAnalysis.disabled = false;
        
        // Clear previous results
        elements.resultSummary.style.display = 'none';
        elements.gapsDetail.style.display = 'none';
        
    } catch (error) {
        alert(`Error loading call: ${error.message}`);
        console.error('Error:', error);
    } finally {
        elements.loadCall.disabled = false;
        elements.loadCall.textContent = 'Load Call';
    }
}

// Run analysis
async function runAnalysis() {
    if (!currentCallId) {
        alert('Please load a call first');
        return;
    }
    
    try {
        // Show loading state
        elements.runAnalysis.disabled = true;
        elements.runAnalysis.textContent = 'Analyzing...';
        
        // Prepare parameters
        const params = {
            thresholdSeconds: parseFloat(elements.thresholdSeconds.value),
            skipStartSeconds: parseFloat(elements.skipStartSeconds.value),
            skipEndSeconds: parseFloat(elements.skipEndSeconds.value),
            minAmplitudeDbfs: parseFloat(elements.minAmplitudeDbfs.value)
        };
        
        // Debug parameters being sent
        console.log('DEBUG - Sending parameters:', params);
        
        // Run analysis
        const response = await fetch(`/api/analyze/${currentCallId}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(params)
        });
        
        if (!response.ok) {
            throw new Error('Analysis failed');
        }
        
        const result = await response.json();
        
        // Debug logging
        console.log('DEBUG - Analysis result received:', result);
        console.log('DEBUG - Evaluation data:', result.evaluation);
        console.log('DEBUG - AI Grade:', result.evaluation.ai_grade);
        console.log('DEBUG - Passed:', result.evaluation.passed);
        console.log('DEBUG - Gap Count:', result.evaluation.gap_count);
        console.log('DEBUG - Database Saved:', result.evaluation.saved_to_database);
        
        // Display results
        displayResults(result);
        
    } catch (error) {
        alert(`Error running analysis: ${error.message}`);
        console.error('Error:', error);
    } finally {
        elements.runAnalysis.disabled = false;
        elements.runAnalysis.textContent = 'Run Analysis';
    }
}

// Display analysis results
function displayResults(result) {
    const evaluation = result.evaluation;
    
    // Show result summary
    elements.resultSummary.style.display = 'block';
    
    // Human grade
    elements.humanGrade.textContent = evaluation.human_grade || 'N/A';
    
    // AI grade with better formatting - use the server's passed value, not ai_grade
    const passed = evaluation.passed;  // Use the server's calculation
    if (passed) {
        elements.aiGrade.textContent = 'PASSED ✓';
        elements.aiGrade.className = 'value evaluation-grade passed';
    } else {
        elements.aiGrade.textContent = 'FAILED ✗ (Dead Air Detected)';
        elements.aiGrade.className = 'value evaluation-grade failed';
    }
    
    // Match status
    const humanGrade = evaluation.human_grade;
    const aiGrade = evaluation.ai_grade;
    if (humanGrade && humanGrade !== 'N/A') {
        const isMatch = humanGrade.toLowerCase() === aiGrade.toLowerCase();
        if (isMatch) {
            elements.matchStatus.textContent = '✓ MATCH';
            elements.matchStatus.className = 'value match-status match';
        } else {
            elements.matchStatus.textContent = '✗ MISMATCH';
            elements.matchStatus.className = 'value match-status mismatch';
        }
    } else {
        elements.matchStatus.textContent = 'No human grade available';
        elements.matchStatus.className = 'value';
        elements.matchStatus.style.color = '#666';
    }
    
    // Other values
    elements.gapsFound.textContent = evaluation.gap_count;
    elements.totalDeadAir.textContent = `${evaluation.total_dead_air_seconds.toFixed(1)}s`;
    elements.audioDuration.textContent = `${evaluation.audio_duration.toFixed(1)}s`;
    
    // Show database save status
    if (evaluation.saved_to_database) {
        elements.databaseStatus.textContent = '✓ Saved to database';
        elements.databaseStatus.style.color = '#27ae60';
    } else {
        elements.databaseStatus.textContent = '✗ Not saved (check server console for errors)';
        elements.databaseStatus.style.color = '#e74c3c';
    }
    
    // Debug logging for display
    console.log('DEBUG - Displaying results:');
    console.log('  Passed value:', passed);
    console.log('  AI Grade:', evaluation.ai_grade);
    console.log('  Gap Count:', evaluation.gap_count);
    
    // Clear existing regions
    regions.clearRegions();
    
    // Add evaluation boundaries (gray areas)
    const boundaries = evaluation.evaluation_boundaries;
    const duration = wavesurfer.getDuration();
    
    // Skip start region
    if (boundaries.start_time > 0) {
        regions.addRegion({
            start: 0,
            end: boundaries.start_time,
            color: 'rgba(150, 150, 150, 0.3)',
            drag: false,
            resize: false
        });
    }
    
    // Skip end region
    if (boundaries.end_time < duration) {
        regions.addRegion({
            start: boundaries.end_time,
            end: duration,
            color: 'rgba(150, 150, 150, 0.3)',
            drag: false,
            resize: false
        });
    }
    
    // Add dead air gaps (red regions)
    evaluation.found_references.forEach((gap, index) => {
        regions.addRegion({
            start: gap.start_time,
            end: gap.end_time,
            color: 'rgba(231, 76, 60, 0.5)',
            drag: false,
            resize: false,
            id: `gap_${index}`
        });
    });
    
    // Display gap details
    if (evaluation.gap_count > 0) {
        elements.gapsDetail.style.display = 'block';
        elements.gapsList.innerHTML = '';
        
        evaluation.found_references.forEach((gap, index) => {
            const gapDiv = document.createElement('div');
            gapDiv.className = 'gap-item';
            gapDiv.innerHTML = `
                <strong>Gap ${index + 1}:</strong> 
                ${gap.duration.toFixed(1)}s duration 
                (${formatTime(gap.start_time)} - ${formatTime(gap.end_time)})
            `;
            elements.gapsList.appendChild(gapDiv);
        });
    } else {
        elements.gapsDetail.style.display = 'none';
    }
}

// Audio control handlers
function playPause() {
    if (wavesurfer) {
        wavesurfer.playPause();
    }
}

function stop() {
    if (wavesurfer) {
        wavesurfer.stop();
    }
}

// Keyboard shortcuts
document.addEventListener('keydown', (e) => {
    if (!wavesurfer) return;
    
    switch(e.key) {
        case ' ':
            e.preventDefault();
            playPause();
            break;
        case 'ArrowLeft':
            e.preventDefault();
            wavesurfer.skip(-5);
            break;
        case 'ArrowRight':
            e.preventDefault();
            wavesurfer.skip(5);
            break;
        case 'Escape':
            e.preventDefault();
            stop();
            break;
    }
});

// Event listeners
elements.loadCall.addEventListener('click', loadCall);
elements.runAnalysis.addEventListener('click', runAnalysis);
elements.playPauseBtn.addEventListener('click', playPause);
elements.stopBtn.addEventListener('click', stop);

// Allow Enter key in call ID input
elements.callId.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
        loadCall();
    }
});

// Initialize
initializeParameterDisplays();