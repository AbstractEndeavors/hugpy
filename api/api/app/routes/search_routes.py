from ..functions import *
from ..functions.search import *
search_bp,logger = get_bp("search_bp",__name__)
@search_bp.route("/search", methods=["POST"])
def search_models(
    q: str = Query(..., min_length=1),
    limit: int = Query(default=20, ge=1, le=100),
    author: str | None = None,
    task: str | None = None,
) -> list[ModelSearchResult]:
    models = api.list_models(
        search=q,
        author=author,
        filter=task,
        limit=limit,
        full=False,
    )

    results: list[ModelSearchResult] = []

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
            )
        )

    return results
