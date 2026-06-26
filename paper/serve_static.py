"""Entry point for preview — launches the competition FastAPI server on port 8080"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uvicorn
from paper.competition_server import app

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
