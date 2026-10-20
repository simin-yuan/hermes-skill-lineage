"""Test fixture: a ``fetch_page`` tool returning canned pages, standing in for a web tool."""
import json
import os


def register(ctx):
    pages = json.loads(os.environ.get("FIXTURE_PAGES", "{}"))

    def fetch_page(args, **_):
        url = (args or {}).get("url", "")
        return json.dumps({"url": url, "content": pages.get(url, "not found")})

    ctx.register_tool(name="fetch_page", toolset="fixture_web", description="Fetch a web page",
                      schema={"name": "fetch_page", "description": "Fetch a web page",
                              "parameters": {"type": "object", "properties": {"url": {"type": "string"}},
                                             "required": ["url"]}},
                      handler=fetch_page)
