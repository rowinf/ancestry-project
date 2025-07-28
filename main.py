from app import app
import os

if __name__ == "__main__":
    # Get port from environment or default to 5000
    port = int(os.environ.get('PORT', 5000))
    
    # Get host from environment or default to localhost
    host = os.environ.get('HOST', '127.0.0.1')
    
    # Run the app
    app.run(
        host=host,
        port=port,
        debug=os.environ.get('FLASK_ENV') == 'development',
        threaded=True
    )
