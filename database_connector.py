import os
import json
import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor
from datetime import datetime
from typing import List, Dict, Optional
from dotenv import load_dotenv
import io
from pydub import AudioSegment


class DatabaseConnector:
    def __init__(self):
        """Initialize database connection using environment variables"""
        load_dotenv()
        
        self.db_config = {
            'host': os.getenv('DEV_DB_HOST'),
            'database': os.getenv('DEV_DB_NAME'),
            'user': os.getenv('DEV_DB_USER'),
            'password': os.getenv('DEV_DB_PASS'),
            'port': 5432
        }
        
        self.connection = None
        self.cursor = None
    
    def connect(self):
        """Establish database connection"""
        try:
            self.connection = psycopg2.connect(**self.db_config)
            self.cursor = self.connection.cursor(cursor_factory=RealDictCursor)
            print(f"Connected to database: {self.db_config['database']}")
        except Exception as e:
            print(f"Error connecting to database: {e}")
            raise
    
    def disconnect(self):
        """Close database connection"""
        if self.cursor:
            self.cursor.close()
        if self.connection:
            self.connection.close()
            print("Disconnected from database")
    
    def fetch_audio_content(self, call_id: int) -> Optional[Dict]:
        """
        Fetch audio content and transcription for a specific call
        
        Args:
            call_id: The call ID to fetch
            
        Returns:
            Dictionary containing audio_content, transcription, and metadata
        """
        try:
            query = """
                SELECT call_id, transcription, human_grade, audio_content, created_at
                FROM dead_air.transcriptions_gemini
                WHERE call_id = %s
            """
            
            self.cursor.execute(query, (call_id,))
            result = self.cursor.fetchone()
            
            if result:
                print(f"Fetched audio content for call_id: {call_id}")
                return dict(result)
            else:
                print(f"No audio content found for call_id: {call_id}")
                return None
                
        except Exception as e:
            print(f"Error fetching audio content: {e}")
            raise
    
    def fetch_calls_with_audio(self, limit: Optional[int] = None, skip_evaluated: bool = True) -> List[Dict]:
        """
        Fetch calls that have audio content
        
        Args:
            limit: Optional limit on number of records to fetch
            skip_evaluated: If True, skip calls that have already been evaluated
            
        Returns:
            List of call records with audio
        """
        try:
            if skip_evaluated:
                query = """
                    SELECT t.call_id, t.transcription, t.human_grade, 
                           t.audio_content IS NOT NULL as has_audio, t.created_at
                    FROM dead_air.transcriptions_gemini t
                    LEFT JOIN dead_air.evaluation_gemini e ON t.call_id = e.call_id
                    WHERE t.audio_content IS NOT NULL
                    AND t.human_grade IS NOT NULL
                    AND t.human_grade IN ('Yes', 'No')
                    AND e.call_id IS NULL
                    ORDER BY t.call_id
                """
            else:
                query = """
                    SELECT call_id, transcription, human_grade, 
                           audio_content IS NOT NULL as has_audio, created_at
                    FROM dead_air.transcriptions_gemini
                    WHERE audio_content IS NOT NULL
                    AND human_grade IS NOT NULL
                    AND human_grade IN ('Yes', 'No')
                    ORDER BY call_id
                """
            
            if limit:
                query += f" LIMIT {limit}"
            
            self.cursor.execute(query)
            results = self.cursor.fetchall()
            
            print(f"Found {len(results)} calls with audio content")
            return [dict(row) for row in results]
            
        except Exception as e:
            print(f"Error fetching calls with audio: {e}")
            raise
    
    def convert_audio_to_pydub(self, audio_content) -> AudioSegment:
        """
        Convert database audio content (WAV bytes/memoryview) to pydub AudioSegment
        
        Args:
            audio_content: Raw audio bytes or memoryview from database
            
        Returns:
            AudioSegment object
        """
        try:
            # Convert memoryview to bytes if needed
            if isinstance(audio_content, memoryview):
                audio_content = bytes(audio_content)
            
            # Create a BytesIO object from the audio content
            audio_io = io.BytesIO(audio_content)
            
            # Load as AudioSegment (assuming WAV format)
            audio_segment = AudioSegment.from_wav(audio_io)
            
            return audio_segment
            
        except Exception as e:
            print(f"Error converting audio content: {e}")
            # Try other formats if WAV fails
            try:
                audio_io = io.BytesIO(audio_content)
                audio_segment = AudioSegment.from_file(audio_io)
                return audio_segment
            except:
                raise e
    
    def insert_evaluation(self, evaluation: Dict) -> bool:
        """
        Insert evaluation results into evaluation_gemini table
        (Compatible with main database format)
        
        Args:
            evaluation: Dictionary containing evaluation results
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Use call_id as transcription_id (matching main database format)
            transcription_id = evaluation['call_id']
            
            query = """
                INSERT INTO dead_air.evaluation_gemini (
                    transcription_id, call_id, intern_ai_grade, score, max_score,
                    criteria, passed, explanation, improvement_suggestion,
                    found_references, context, original_transcription, created_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (transcription_id) DO UPDATE SET
                    intern_ai_grade = EXCLUDED.intern_ai_grade,
                    score = EXCLUDED.score,
                    max_score = EXCLUDED.max_score,
                    criteria = EXCLUDED.criteria,
                    passed = EXCLUDED.passed,
                    explanation = EXCLUDED.explanation,
                    improvement_suggestion = EXCLUDED.improvement_suggestion,
                    found_references = EXCLUDED.found_references,
                    context = EXCLUDED.context,
                    original_transcription = EXCLUDED.original_transcription,
                    created_at = EXCLUDED.created_at
            """
            
            self.cursor.execute(query, (
                transcription_id,
                evaluation['call_id'],
                evaluation['intern_ai_grade'],
                evaluation['score'],
                evaluation['max_score'],
                evaluation['criteria'],
                evaluation['passed'],
                evaluation['explanation'],
                evaluation.get('improvement_suggestion'),
                json.dumps(evaluation['found_references']),
                evaluation['context'],
                evaluation['original_transcription'],
                datetime.now()
            ))
            
            self.connection.commit()
            print(f"Inserted evaluation for call_id: {evaluation['call_id']}")
            return True
            
        except Exception as e:
            print(f"Error inserting evaluation for call_id {evaluation['call_id']}: {e}")
            self.connection.rollback()
            return False
    
    def get_evaluation_statistics(self) -> Dict:
        """
        Get statistics comparing audio-based evaluations with human grades
        
        Returns:
            Dictionary with comparison statistics
        """
        try:
            query = """
                WITH audio_evaluations AS (
                    SELECT 
                        t.call_id,
                        CASE 
                            WHEN LOWER(t.human_grade) = 'yes' THEN true
                            WHEN LOWER(t.human_grade) = 'no' THEN false
                            ELSE NULL
                        END AS human_graded,
                        e.passed AS audio_graded
                    FROM dead_air.transcriptions_gemini t
                    JOIN dead_air.evaluation_gemini e ON e.call_id = t.call_id
                    WHERE LOWER(t.human_grade) IN ('yes', 'no')
                    AND e.context = 'audio_analysis'
                )
                SELECT 
                    COUNT(*) AS total_comparisons,
                    SUM(CASE WHEN human_graded = true AND audio_graded = true THEN 1 ELSE 0 END) AS true_positives,
                    SUM(CASE WHEN human_graded = false AND audio_graded = false THEN 1 ELSE 0 END) AS true_negatives,
                    SUM(CASE WHEN human_graded = false AND audio_graded = true THEN 1 ELSE 0 END) AS false_positives,
                    SUM(CASE WHEN human_graded = true AND audio_graded = false THEN 1 ELSE 0 END) AS false_negatives,
                    ROUND(
                        SUM(CASE WHEN human_graded = audio_graded THEN 1 ELSE 0 END)::numeric / 
                        COUNT(*)::numeric * 100, 2
                    ) AS accuracy_percentage
                FROM audio_evaluations
            """
            
            self.cursor.execute(query)
            result = self.cursor.fetchone()
            
            return dict(result) if result else {}
            
        except Exception as e:
            print(f"Error getting audio evaluation statistics: {e}")
            raise