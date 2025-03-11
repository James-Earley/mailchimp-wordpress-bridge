import os
from flask import Flask
from api.webhook_routes import webhook_bp
from config import validate_config, PORT

def create_app():
    """Create and configure the Flask application."""
    app = Flask(__name__)
    
    # Register blueprints
    app.register_blueprint(webhook_bp)
    
    # Register error handlers
    @app.errorhandler(404)
    def not_found(error):
        return {"error": "Endpoint not found"}, 404

    @app.errorhandler(500)
    def server_error(error):
        return {"error": "Internal server error"}, 500
    
    return app

# Create the app
app = create_app()

# This is for running the app locally
if __name__ == '__main__':
    # Validate configuration on startup
    validate_config()
    
    # Run the app
    app.run(host='0.0.0.0', port=PORT)