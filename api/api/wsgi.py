from app import *
import app.routes as routes
get_Flask_app(name="6092_abstractgpt_api",routes=routes, allowed_origins=["https://dev.abstractgpt.ai/*","https://abstractgpt.ai/*","https://api.abstractgpt.ai/*"],debug=True)
