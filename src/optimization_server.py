from flask import Flask, request, jsonify
from flask_cors import CORS
import sys
import os
import configparser

current_dir = os.path.dirname(os.path.abspath(__file__))
src_path = os.path.join(current_dir, 'src')
sys.path.insert(0, src_path)

# import main
from optimization.main import main as optimization_main

app = Flask(__name__)
CORS(app)

@app.route('/api/optimization', methods=['POST'])
def optimization_endpoint():
    try:
        # get request_data
        request_data = request.get_json()

        if not request_data:
            return jsonify({
                'success': False,
                'error': 'Request data is empty'
            }), 400

        # Parse request data
        required = [
            'id',
            'system_under_test',
            'status',
            'project_name',
            'project',
            'edit_description'
        ]
        missing = [k for k in required if k not in request_data]
        if missing:
            return jsonify({
                'success': False,
                'error': f"Missing required parameters: {', '.join(missing)}"
            }), 400

        json_input = {
            'id': request_data['id'],
            'system_under_test': request_data['system_under_test'],
            'status': request_data['status'],
            'project_name': request_data['project_name'],
            'project': request_data['project'],
            'edit_description': request_data['edit_description']
        }

        response_message = optimization_main(json_input)
        return jsonify({ 'success': True, 'data': response_message })
    
    except Exception as e:
        print(f"Error processing optimization request: {str(e)}")
        return jsonify({ 'success': False, 'error': f'Internal server error: {str(e)}' }), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({ 'success': True, 'message': 'Optimization server running' })

if __name__ == '__main__':
    print('Starting Optimization Flask server...')

    config = configparser.ConfigParser()
    config_path = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'server_config.ini'))
    config.read(config_path)
    
    host = config['DEFAULT']['ListenHost']
    port = int(config['DEFAULT']['OptimizationPort'])

    print(f'Optimization server will start on {host}:{port}')

    try:
        from waitress import serve
        serve(app, host=host, port=port)
        print("Server closed.")
    except Exception as e:
        print(f"Failed to start server: {e}")

