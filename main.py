#!/usr/bin/env python3
"""
Dead Air Detection using Audio-DeSilencer
Main CLI driver for processing audio files from database
"""

import argparse
import sys
import json
from datetime import datetime
from typing import Optional, Dict, List
from database_connector import DatabaseConnector
from audio_desilencer.audio_processor import AudioProcessor
import tempfile
import os


class DeadAirDetector:
    def __init__(self, db_connector: DatabaseConnector):
        self.db = db_connector
        
    def evaluate_call(self, call_id: int, threshold_seconds: float = 5.0, 
                     skip_start_seconds: float = 10.0, skip_end_seconds: float = 10.0,
                     min_amplitude_dbfs: float = -30.0) -> Dict:
        """
        Evaluate a single call for dead air using audio analysis
        
        Args:
            call_id: Call ID to evaluate
            threshold_seconds: Minimum silence duration to consider as dead air
            skip_start_seconds: Seconds to skip from start
            skip_end_seconds: Seconds to skip from end
            min_amplitude_dbfs: Minimum amplitude threshold in dBFS
            
        Returns:
            Evaluation results dictionary
        """
        # Fetch call data with audio
        call_data = self.db.fetch_audio_content(call_id)
        if not call_data:
            print(f"No data found for call_id: {call_id}")
            return None
            
        if not call_data.get('audio_content'):
            print(f"No audio content found for call_id: {call_id}")
            return None
        
        # Convert audio content to AudioSegment
        try:
            audio_segment = self.db.convert_audio_to_pydub(call_data['audio_content'])
            
            # Create temporary file for AudioProcessor
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp_file:
                temp_path = tmp_file.name
                audio_segment.export(temp_path, format='wav')
            
            # Create AudioProcessor instance
            processor = AudioProcessor(temp_path)
            
            # Detect dead air
            dead_air_result = processor.detect_dead_air(
                min_silence_len=int(threshold_seconds * 1000),
                threshold=int(min_amplitude_dbfs),
                skip_start_ms=int(skip_start_seconds * 1000),
                skip_end_ms=int(skip_end_seconds * 1000)
            )
            
            # Clean up temp file
            os.unlink(temp_path)
            
            # Determine if call passed or failed
            passed = dead_air_result['total_gaps'] == 0
            
            # Create evaluation result
            evaluation = {
                'call_id': call_id,
                'intern_ai_grade': 'No' if passed else 'Yes',  # Yes = has dead air
                'passed': passed,
                'score': 0 if passed else dead_air_result['total_gaps'],
                'max_score': 0,
                'criteria': f'Audio-based dead air detection (threshold: {threshold_seconds}s)',
                'explanation': self._generate_explanation(dead_air_result),
                'found_references': {
                    'gaps': dead_air_result['gaps'],
                    'total_dead_air_seconds': dead_air_result['total_dead_air_seconds'],
                    'evaluation_boundaries': dead_air_result['evaluation_boundaries'],
                    'parameters': dead_air_result['parameters'],
                    'audio_duration_seconds': dead_air_result['audio_duration_seconds']
                },
                'context': 'audio_analysis',
                'original_transcription': call_data.get('transcription', '')[:500]  # First 500 chars
            }
            
            return evaluation
            
        except Exception as e:
            print(f"Error processing audio for call_id {call_id}: {e}")
            return None
    
    def _generate_explanation(self, dead_air_result: Dict) -> str:
        """Generate human-readable explanation of results"""
        if dead_air_result['total_gaps'] == 0:
            return "No dead air gaps detected in the audio."
        
        gaps_desc = []
        for i, gap in enumerate(dead_air_result['gaps'][:3]):  # Show first 3 gaps
            gaps_desc.append(f"Gap {i+1}: {gap['duration']:.1f}s at {gap['start_time']:.1f}s")
        
        if dead_air_result['total_gaps'] > 3:
            gaps_desc.append(f"... and {dead_air_result['total_gaps'] - 3} more gaps")
        
        return (f"Found {dead_air_result['total_gaps']} dead air gap(s) totaling "
                f"{dead_air_result['total_dead_air_seconds']:.1f} seconds. " + 
                "; ".join(gaps_desc))
    
    def process_batch(self, limit: Optional[int] = None, skip_evaluated: bool = True,
                     threshold_seconds: float = 5.0, skip_start_seconds: float = 10.0,
                     skip_end_seconds: float = 10.0, min_amplitude_dbfs: float = -30.0) -> Dict:
        """
        Process a batch of calls
        
        Returns:
            Summary statistics
        """
        # Fetch calls with audio
        calls = self.db.fetch_calls_with_audio(limit=limit, skip_evaluated=skip_evaluated)
        
        if not calls:
            print("No calls found to process")
            return {'processed': 0, 'successful': 0, 'failed': 0}
        
        print(f"Processing {len(calls)} calls...")
        
        stats = {
            'processed': 0,
            'successful': 0,
            'failed': 0,
            'with_dead_air': 0,
            'without_dead_air': 0,
            'errors': []
        }
        
        for call in calls:
            call_id = call['call_id']
            print(f"\nProcessing call_id: {call_id}")
            
            try:
                evaluation = self.evaluate_call(
                    call_id, 
                    threshold_seconds=threshold_seconds,
                    skip_start_seconds=skip_start_seconds,
                    skip_end_seconds=skip_end_seconds,
                    min_amplitude_dbfs=min_amplitude_dbfs
                )
                
                if evaluation:
                    # Save to database
                    if self.db.insert_evaluation(evaluation):
                        stats['successful'] += 1
                        if evaluation['passed']:
                            stats['without_dead_air'] += 1
                            print(f"  Result for call {call_id}: PASSED (No dead air)")
                        else:
                            stats['with_dead_air'] += 1
                            print(f"  Result for call {call_id}: FAILED (Dead air detected)")
                        print(f"  Explanation: {evaluation['explanation']}")
                    else:
                        stats['failed'] += 1
                        stats['errors'].append(f"Failed to save evaluation for call_id: {call_id}")
                        print(f"  Error: Failed to save evaluation for call_id: {call_id}")
                else:
                    stats['failed'] += 1
                    stats['errors'].append(f"Failed to evaluate call_id: {call_id}")
                    print(f"  Error: Failed to evaluate call_id: {call_id}")
                    
            except Exception as e:
                stats['failed'] += 1
                stats['errors'].append(f"Error with call_id {call_id}: {str(e)}")
            
            stats['processed'] += 1
            
            # Progress update
            if stats['processed'] % 10 == 0:
                print(f"Progress: {stats['processed']}/{len(calls)} calls processed")
        
        return stats


def main():
    parser = argparse.ArgumentParser(
        description='Dead Air Detection using Audio Analysis',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process a single call
  python main.py --call-id 12345
  
  # Process batch with custom threshold
  python main.py --limit 100 --threshold 5.0
  
  # View statistics only
  python main.py --stats-only
  
  # Reprocess all calls
  python main.py --reprocess --limit 50
        """
    )
    
    # Processing options
    parser.add_argument('--call-id', type=int, help='Process a specific call ID')
    parser.add_argument('--limit', type=int, help='Limit number of calls to process')
    parser.add_argument('--reprocess', action='store_true', 
                       help='Reprocess calls that have already been evaluated')
    parser.add_argument('--stats-only', action='store_true', 
                       help='Show statistics without processing')
    
    # Detection parameters
    parser.add_argument('--threshold', type=float, default=5.0,
                       help='Dead air threshold in seconds (default: 5.0)')
    parser.add_argument('--skip-start', type=float, default=10.0,
                       help='Seconds to skip from start (default: 10.0)')
    parser.add_argument('--skip-end', type=float, default=10.0,
                       help='Seconds to skip from end (default: 10.0)')
    parser.add_argument('--min-amplitude', type=float, default=-30.0,
                       help='Minimum amplitude threshold in dBFS (default: -30.0)')
    
    args = parser.parse_args()
    
    # Initialize database connection
    db = DatabaseConnector()
    detector = DeadAirDetector(db)
    
    try:
        db.connect()
        
        if args.stats_only:
            # Show statistics
            stats = db.get_evaluation_statistics()
            print("\nAudio Dead Air Detection Statistics:")
            print("=" * 50)
            for key, value in stats.items():
                print(f"{key}: {value}")
                
        elif args.call_id:
            # Process single call
            print(f"Processing call_id: {args.call_id}")
            evaluation = detector.evaluate_call(
                args.call_id,
                threshold_seconds=args.threshold,
                skip_start_seconds=args.skip_start,
                skip_end_seconds=args.skip_end,
                min_amplitude_dbfs=args.min_amplitude
            )
            
            if evaluation:
                print("\nEvaluation Results:")
                print("=" * 50)
                print(f"Call ID: {evaluation['call_id']}")
                print(f"Dead Air Detected: {'Yes' if not evaluation['passed'] else 'No'}")
                print(f"Number of Gaps: {len(evaluation['found_references']['gaps'])}")
                print(f"Total Dead Air: {evaluation['found_references']['total_dead_air_seconds']:.1f}s")
                print(f"Explanation: {evaluation['explanation']}")
                
                # Save to database
                if db.insert_evaluation(evaluation):
                    print("\nEvaluation saved to database successfully")
                else:
                    print("\nFailed to save evaluation to database")
            else:
                print("Failed to evaluate call")
                
        else:
            # Process batch
            stats = detector.process_batch(
                limit=args.limit,
                skip_evaluated=not args.reprocess,
                threshold_seconds=args.threshold,
                skip_start_seconds=args.skip_start,
                skip_end_seconds=args.skip_end,
                min_amplitude_dbfs=args.min_amplitude
            )
            
            print("\nProcessing Summary:")
            print("=" * 50)
            print(f"Total Processed: {stats['processed']}")
            print(f"Successful: {stats['successful']}")
            print(f"Failed: {stats['failed']}")
            print(f"With Dead Air: {stats['with_dead_air']}")
            print(f"Without Dead Air: {stats['without_dead_air']}")
            
            if stats['errors']:
                print("\nErrors:")
                for error in stats['errors'][:10]:  # Show first 10 errors
                    print(f"  - {error}")
                if len(stats['errors']) > 10:
                    print(f"  ... and {len(stats['errors']) - 10} more errors")
    
    except KeyboardInterrupt:
        print("\nProcess interrupted by user")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
    finally:
        db.disconnect()


if __name__ == "__main__":
    main()