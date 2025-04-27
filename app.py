import os
import re
import logging
import json # To potentially capture detailed error info from yt-dlp
import yt_dlp # Import the new library
from flask import Flask, request, render_template, send_file, flash, redirect, url_for, session

    # --- Configuration ---
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DOWNLOAD_FOLDER = os.path.join(BASE_DIR, 'downloads')
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    # --- Flask App Initialization ---
app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_very_secret_key_12345' # Change this!

    # --- Helper Function ---
def sanitize_filename(filename):
        """Removes or replaces characters problematic in filenames."""
        sanitized = re.sub(r'[\\/*?:"<>|]', "", filename)
        sanitized = sanitized.replace(" ", "_")
        # yt-dlp might add ID in brackets, remove that too if present
        sanitized = re.sub(r'\[[\w-]{11}\]', '', sanitized).strip()
        return sanitized[:100] # Limit length

    # --- Routes ---
@app.route('/')
def index():
        """Renders the main page."""
        logging.info("Rendering index page.")
        return render_template('index.html')

@app.route('/download', methods=['POST'])
def download_audio():
        """Handles the download request using yt-dlp."""
        youtube_url = request.form.get('youtube_url')
        if not youtube_url:
            flash('Error: No YouTube URL provided.', 'error')
            logging.warning("Download attempt failed: No URL provided.")
            return redirect(url_for('index'))

        logging.info(f"Received download request for URL: {youtube_url}")
        output_filepath = None # To keep track of the final mp3 file

        try:
            # --- Configure yt-dlp options ---
            # Create a temporary filename template using a session or unique ID
            # to avoid collisions if multiple users access simultaneously.
            # For simplicity here, we'll use a base name and let yt-dlp handle uniqueness if needed.
            # A more robust solution might involve uuid.uuid4()
            temp_filename_base = os.path.join(DOWNLOAD_FOLDER, "audio_download")

            ydl_opts = {
                'format': 'bestaudio/best', # Choose best audio-only format
                'outtmpl': f'{temp_filename_base}.%(ext)s', # Output template BEFORE conversion
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio', # Use FFmpeg to extract audio
                    'preferredcodec': 'mp3',     # Convert to mp3
                    'preferredquality': '192',   # Set bitrate to 192k
                }],
                'noplaylist': True, # Don't download playlists if a playlist URL is given
                'logger': logging.getLogger('yt_dlp'), # Integrate yt-dlp logs with Flask logs
                'progress_hooks': [lambda d: logging.info(f"yt-dlp status: {d.get('status')}, filename: {d.get('filename')}") if d.get('status') == 'downloading' else None], # Log download progress
                'nocheckcertificate': True, # Sometimes needed for network issues, use with caution
                # 'verbose': True, # Uncomment for very detailed yt-dlp logs during debugging
            }

            logging.info(f"Using yt-dlp options: { {k: v for k, v in ydl_opts.items() if k != 'logger'} }") # Log options except logger object

            # --- Download and Convert using yt-dlp ---
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                logging.info("Running yt-dlp download...")
                # Run the download. yt-dlp handles calling FFmpeg.
                info_dict = ydl.extract_info(youtube_url, download=True)
                # After conversion, the file extension might change to mp3
                # We need to figure out the final filename.
                # yt-dlp usually puts info in info_dict, but postprocessor path isn't always obvious.
                # Safer bet: find the mp3 file in the download folder.

                # Get sanitized title for the download filename
                video_title = info_dict.get('title', 'downloaded_audio')
                safe_title = sanitize_filename(video_title)
                expected_mp3_filename = f"{safe_title}.mp3" # Construct expected final name

                # Find the actual downloaded MP3 file
                # Check the template base name first, then the title-based name
                possible_original_file = f"{temp_filename_base}.mp3"
                possible_titled_file = os.path.join(DOWNLOAD_FOLDER, f"{safe_title}.mp3") # yt-dlp might rename based on title

                if os.path.exists(possible_original_file):
                     # yt-dlp might rename the original template file after conversion
                     final_mp3_path_temp = os.path.join(DOWNLOAD_FOLDER, expected_mp3_filename)
                     try:
                         # Rename the downloaded file to use the video title
                         os.rename(possible_original_file, final_mp3_path_temp)
                         output_filepath = final_mp3_path_temp
                         logging.info(f"Renamed downloaded file to: {output_filepath}")
                     except OSError as rename_err:
                         logging.warning(f"Could not rename {possible_original_file} to {final_mp3_path_temp}: {rename_err}. Using original name.")
                         output_filepath = possible_original_file # Use the original name if rename fails
                elif os.path.exists(possible_titled_file):
                    # If yt-dlp already created the file with the title
                    output_filepath = possible_titled_file
                    logging.info(f"Found downloaded file with title: {output_filepath}")
                else:
                    # Fallback: search for *any* mp3 file in downloads (less reliable)
                    found_files = [f for f in os.listdir(DOWNLOAD_FOLDER) if f.endswith('.mp3')]
                    if found_files:
                        output_filepath = os.path.join(DOWNLOAD_FOLDER, found_files[0])
                        logging.warning(f"Could not find expected file, using first found mp3: {output_filepath}")
                    else:
                         raise FileNotFoundError("Could not find the converted MP3 file.")


                logging.info(f"Download and conversion successful. MP3 path: {output_filepath}")


            # --- Send MP3 File to User ---
            logging.info(f"Sending MP3 file: {output_filepath}")
            # Use send_file to send the MP3 as an attachment
            return send_file(
                output_filepath,
                as_attachment=True,
                # Use the sanitized title for the download name the user sees
                download_name=os.path.basename(output_filepath)
            )

        except yt_dlp.utils.DownloadError as e:
            # Handle specific yt-dlp errors
            flash(f'Error during download: {e}', 'error')
            logging.error(f"yt-dlp download error for {youtube_url}: {e}", exc_info=True)
            return redirect(url_for('index'))
        except FileNotFoundError as e:
             flash('Error: Could not locate the converted MP3 file after download.', 'error')
             logging.error(f"File not found error after download for {youtube_url}: {e}", exc_info=True)
             return redirect(url_for('index'))
        except Exception as e:
            # Catch any other unexpected errors
            flash(f'An unexpected error occurred: {e}', 'error')
            logging.error(f"Unexpected error for {youtube_url}: {e}", exc_info=True)
            return redirect(url_for('index'))

        finally:
            # --- Cleanup ---
            # Delete the final MP3 file after sending it
            if output_filepath and os.path.exists(output_filepath):
                try:
                    # Add a small delay IF needed, though usually not necessary with send_file
                    # import time; time.sleep(1)
                    os.remove(output_filepath)
                    logging.info(f"Cleaned up temporary file: {output_filepath}")
                except OSError as e:
                    logging.error(f"Error removing temporary file {output_filepath}: {e}")
            # Also clean up any intermediate files yt-dlp might leave (e.g., .webm, .m4a)
            # This is a simple cleanup, might need refinement
            for item in os.listdir(DOWNLOAD_FOLDER):
                if item.startswith("audio_download.") and not item.endswith(".mp3"): # Clean up original downloads
                     item_path = os.path.join(DOWNLOAD_FOLDER, item)
                     try:
                         os.remove(item_path)
                         logging.info(f"Cleaned up intermediate file: {item_path}")
                     except OSError as e:
                         logging.error(f"Error removing intermediate file {item_path}: {e}")


    # --- Run the App ---
if __name__ == '__main__':
        app.run(host='0.0.0.0', port=5000, debug=True) # Keep debug=True for local testing
    