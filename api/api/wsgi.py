from abstract_hugpy.flask_app import get_hugpy_flask
app = get_hugpy_flask(
    name="6092_abstractgpt_api",
    allowed_origins=["https://dev.abstractgpt.ai/*",
                     "https://abstractgpt.ai/*",
                     "https://api.abstractgpt.ai/*"
                     ],
    debug=True
    )
