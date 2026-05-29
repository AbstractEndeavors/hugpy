from ..functions import *
from ..functions.search import *
from flask import request, jsonify, abort

search_bp,logger = get_bp("search_bp",__name__)


@search_bp.route("/search",methods=["GET"])
def search_models():
    q = request.args.get("q", "")
    if not q:
        abort(400, description="Query parameter 'q' is required.")

    limit = request.args.get("limit", default=20, type=int)
    author = request.args.get("author")
    task = request.args.get("task")

    try:
        models = api.list_models(
            search=q,
            author=author,
            filter=task,
            limit=limit,
            full=False,
        )
    except Exception as exc:
        # HF can reject the request (e.g. 401 Invalid username or password when
        # the HF token is missing/invalid). Surface that as a clean JSON error
        # the UI can display, instead of letting it bubble up as a 500/HTML page.
        abort(502, description=f"Hugging Face request failed: {exc}")

    results = []

    for model in models:
        results.append(
            ModelSearchResult(
                hub_id=model.modelId,
                author=getattr(model, "author", None),
                downloads=getattr(model, "downloads", None),
                likes=getattr(model, "likes", None),
                tags=getattr(model, "tags", []) or [],
                pipeline_tag=getattr(model, "pipeline_tag", None),
                library_name=getattr(model, "library_name", None),
                private=getattr(model, "private", None),
            ).model_dump()
        )

    return jsonify(results)
