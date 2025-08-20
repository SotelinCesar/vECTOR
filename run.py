import logging

from app import create_app


app = create_app()

if __name__ == "__main__":
    logging.info("Flask app started")
    app.run(host="0.0.0.0", port=8000)


#Comandos 
#python -m venv venv
# .\venv\Scripts\Activate.ps1
# pip install -r requirements.txt
# python .\start\whatsapp_quickstart.py
# python run.py
#########################################
# ngrok http 8000 --url=frog-new-satyr.ngrok-free.app
#
#
