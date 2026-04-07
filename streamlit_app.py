import sys
import os

# Add the cme-engine subfolder to the path so imports work on Streamlit Cloud
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "cme-engine"))

# Now run the actual app
exec(open(os.path.join(os.path.dirname(__file__), "cme-engine", "app", "app.py")).read())
