from flask import Flask, request, jsonify
from flask_cors import CORS
import sys
import os
import configparser

current_dir = os.path.dirname(os.path.abspath(__file__))
src_path = os.path.join(current_dir, 'src')
sys.path.insert(0, src_path)

# import main
from simulation.main import main

app = Flask(__name__)
CORS(app) 

@app.route('/api/simulate', methods=['POST'])
def simulate():
    try:
        # get request_data
        request_data = request.get_json()
        
        if not request_data:
            return jsonify({
                'success': False,
                'error': 'Request data is empty'
            }), 400
        
        # Parse request data
        commit_url = request_data.get('commit_url')
        system_under_test = request_data.get('system_under_test')
        status = request_data.get('status')
        suggestion_type = request_data.get('suggestion_type')
        
        # Validate required parameters
        if not commit_url or not system_under_test or not status or not suggestion_type:
            return jsonify({
                'success': False,
                'error': 'Missing required parameters: commit_url, system_under_test, status, suggestion_type'
            }), 400
        
        # Construct input for main function
        input_data = {
            "commit_url": commit_url,
            "system_under_test": system_under_test,
            "status": status,
            "suggestion_type": suggestion_type
        }
        
        # Invoke main function
        response_message = main(input_data)
        # return
        return jsonify({
            'success': True,
            'data': response_message
        })
        
    except Exception as e:
        print(f"Error processing request: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Internal server error: {str(e)}'
        }), 500

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        'success': True,
        'message': 'Simulation server running'
    })

if __name__ == '__main__':
    print("Starting Simulation Flask server...")
    
    config = configparser.ConfigParser()
    config_path = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'server_config.ini'))
    config.read(config_path)
    
    host = config['DEFAULT']['ListenHost']
    port = int(config['DEFAULT']['SimulationPort'])

    print(f'Simulation server will start on {host}:{port}')

    try:
        from waitress import serve
        serve(app, host=host, port=port)
        print("Server closed.")
    except Exception as e:
        print(f"Failed to start server: {e}") 